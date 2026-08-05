"""Qt-native Gateway process and HTTP client."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import uuid4

from PySide6.QtCore import QByteArray, QEventLoop, QProcess, QProcessEnvironment, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


class GatewayBridge:
    def __init__(self, parent: Any, *, base_url: str = "http://127.0.0.1:8765") -> None:
        self.base_url = base_url.rstrip("/")
        self.session_id = f"coretest-{uuid4().hex}"
        self.network = QNetworkAccessManager(parent)
        self.process = QProcess(parent)
        self.ready = False
        self._attempts = 0
        self._ready_callbacks: list[Callable[[], None]] = []
        self._error_callbacks: list[Callable[[str], None]] = []
        self._access_token = os.getenv("AI_GATEWAY_ACCESS_TOKEN", "").strip()
        self._host_token = os.getenv("AI_GATEWAY_HOST_TOKEN", "").strip()
        self._poll = QTimer(parent)
        self._poll.setInterval(350)
        self._poll.timeout.connect(self._check_health)

    @property
    def copilot_url(self) -> QUrl:
        url = f"{self.base_url}/copilot-shell/?host_session_id={self.session_id}"
        if self._access_token:
            encoded = QUrl.toPercentEncoding(self._access_token).data().decode()
            url += f"#access_token={encoded}"
        return QUrl(url)

    @property
    def native_agent_url(self) -> QUrl:
        url = f"{self.base_url}/agent-native/?host_session_id={self.session_id}"
        if self._access_token:
            encoded = QUrl.toPercentEncoding(self._access_token).data().decode()
            url += f"#access_token={encoded}"
        return QUrl(url)

    def on_ready(self, callback: Callable[[], None]) -> None:
        self._ready_callbacks.append(callback)

    def on_error(self, callback: Callable[[str], None]) -> None:
        self._error_callbacks.append(callback)

    def start(self) -> None:
        if self.ready:
            return
        gateway_executable = _gateway_executable()
        gateway_src = _gateway_src()
        if gateway_executable is None and gateway_src is None:
            self._fail(
                "当前源码不包含内置 AI Gateway，请重新拉取完整的 CoreTest Agent 分支。"
            )
            return
        environment = QProcessEnvironment.systemEnvironment()
        env_path = _configuration_file(gateway_executable, gateway_src)
        for name, value in _load_env_values(env_path).items():
            if value and not environment.contains(name):
                environment.insert(name, value)
        if gateway_executable is not None:
            _protect_packaged_runtime(environment)
        environment.insert("AI_MODEL_CONFIG_FILE", str(env_path))
        self._access_token = environment.value("AI_GATEWAY_ACCESS_TOKEN").strip()
        self._host_token = environment.value("AI_GATEWAY_HOST_TOKEN").strip()
        environment.insert("PYTHONUNBUFFERED", "1")
        asset_root = _gateway_asset_root(gateway_executable, gateway_src)
        if asset_root is None:
            environment.remove("AI_GATEWAY_ASSET_ROOT")
        else:
            environment.insert("AI_GATEWAY_ASSET_ROOT", str(asset_root))
        self.process.setProcessEnvironment(environment)
        server_args = _server_arguments(self.base_url)
        if gateway_executable is not None:
            self.process.start(str(gateway_executable), server_args)
        else:
            current = environment.value("PYTHONPATH")
            environment.insert(
                "PYTHONPATH",
                f"{gateway_src}{os.pathsep}{current}" if current else str(gateway_src),
            )
            self.process.setProcessEnvironment(environment)
            self.process.start(sys.executable, ["-m", "ai_gateway.server", *server_args])
        self._attempts = 0
        self._poll.start()

    def retry(self) -> None:
        self.stop_process()
        self.ready = False
        self.start()

    def publish(
        self,
        context: dict[str, Any],
        snapshot: dict[str, Any],
        *,
        workspace_root: str | None = None,
        host_bridge: dict[str, str] | None = None,
        complete: Callable[[], None] | None = None,
    ) -> None:
        def publish_context(_result: dict[str, Any] | None = None) -> None:
            self.request(
                "POST",
                "/api/v1/host/context",
                context,
                success=(lambda _response: complete()) if complete else None,
            )

        def publish_snapshot(_result: dict[str, Any] | None = None) -> None:
            self.request(
                "POST",
                "/api/v1/host/snapshot",
                snapshot,
                privileged=True,
                success=publish_context,
            )

        if workspace_root:
            workspace_payload: dict[str, Any] = {"project_root": workspace_root}
            if host_bridge:
                workspace_payload["host_bridge"] = host_bridge
            self.request(
                "POST",
                "/api/v1/host/workspace",
                workspace_payload,
                privileged=True,
                success=publish_snapshot,
            )
        else:
            publish_snapshot()

    def release(self) -> None:
        if self.ready:
            reply = self.request("DELETE", "/api/v1/host/session", privileged=True)
            if reply is not None and not reply.isFinished():
                loop = QEventLoop()
                reply.finished.connect(loop.quit)
                QTimer.singleShot(1500, loop.quit)
                loop.exec()
        self.stop_process()

    def stop_process(self) -> None:
        self._poll.stop()
        self.ready = False
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(1500):
                self.process.kill()

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        privileged: bool = False,
        success: Callable[[dict[str, Any]], None] | None = None,
    ) -> QNetworkReply:
        separator = "&" if "?" in path else "?"
        request = QNetworkRequest(QUrl(f"{self.base_url}{path}{separator}host_session_id={self.session_id}"))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        token = self._host_token if privileged else self._access_token
        if token:
            request.setRawHeader(b"Authorization", f"Bearer {token}".encode())
        body = QByteArray(json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"))
        if method == "GET":
            reply = self.network.get(request)
        elif method == "DELETE":
            reply = self.network.deleteResource(request)
        else:
            reply = self.network.post(request, body)
        reply.finished.connect(lambda: self._finished(reply, success))
        return reply

    def _check_health(self) -> None:
        self._attempts += 1
        request = QNetworkRequest(QUrl(f"{self.base_url}/health"))
        reply = self.network.get(request)
        reply.finished.connect(lambda: self._health_finished(reply))
        if self._attempts >= 30:
            self._poll.stop()
            detail = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace").strip()
            self._fail(detail or "AI Gateway 启动超时")

    def _health_finished(self, reply: QNetworkReply) -> None:
        ok = reply.error() == QNetworkReply.NetworkError.NoError
        reply.deleteLater()
        if ok and not self.ready:
            self.ready = True
            self._poll.stop()
            for callback in self._ready_callbacks:
                callback()

    def _finished(
        self, reply: QNetworkReply, success: Callable[[dict[str, Any]], None] | None
    ) -> None:
        raw = bytes(reply.readAll())
        ok = reply.error() == QNetworkReply.NetworkError.NoError
        error_message = reply.errorString()
        reply.deleteLater()
        if not ok:
            try:
                payload = json.loads(raw.decode("utf-8"))
                message = payload.get("error", {}).get("message")
            except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
                message = None
            self._fail(str(message or error_message or "AI Gateway 请求失败"))
            return
        if ok and success:
            try:
                success(json.loads(raw.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._fail("AI Gateway 返回了无效响应")

    def _fail(self, message: str) -> None:
        for callback in self._error_callbacks:
            callback(message)


def _gateway_src() -> Path | None:
    configured = os.getenv("CORETEST_AI_PLATFORM_ROOT", "").strip()
    embedded = Path(__file__).resolve().parent / "runtime" / "src"
    candidates = [embedded, Path(configured)] if configured else [embedded]
    candidates.extend(Path(__file__).resolve().parents)
    for root in candidates:
        for source in (root, root / "src" / "ai-gateway" / "src"):
            if (source / "ai_gateway" / "server.py").is_file():
                return source
    return None


def _gateway_executable() -> Path | None:
    configured = os.getenv("CORETEST_AI_GATEWAY_EXE", "").strip()
    candidates = [Path(configured)] if configured else []
    app_dir = Path(sys.executable).resolve().parent
    candidates.extend(
        (
            app_dir / "ai-gateway" / "geely-ai-gateway.exe",
            app_dir / "geely-ai-gateway" / "geely-ai-gateway.exe",
            app_dir / "geely-ai-gateway.exe",
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _gateway_asset_root(
    gateway_executable: Path | None, gateway_src: Path | None
) -> Path | None:
    if gateway_executable is not None or gateway_src is None:
        return None
    return gateway_src.parent


def _server_arguments(base_url: str) -> list[str]:
    parsed = urlsplit(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765
    return ["--host", host, "--port", str(port)]


def _load_env_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name:
            values[name] = value.strip()
    return values


def _protect_packaged_runtime(environment: QProcessEnvironment) -> None:
    environment.remove("OPENCODE_COMMAND")
    environment.insert("OPENCODE_ALLOW_DOWNLOAD", "false")


def _configuration_file(
    gateway_executable: Path | None, gateway_src: Path | None
) -> Path:
    configured = os.getenv("AI_MODEL_CONFIG_FILE", "").strip()
    if configured:
        target = Path(configured).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    candidates = [Path.cwd() / "ai-model.env"]
    candidates.extend(parent / "ai-model.env" for parent in Path(__file__).resolve().parents)
    if gateway_executable is not None:
        candidates.append(gateway_executable.parent / "ai-model.env")
        candidates.append(gateway_executable.parent / ".env")
    if gateway_src is not None:
        candidates.append(gateway_src.parent / "ai-model.env")
    candidates.extend(parent / ".env" for parent in Path(__file__).resolve().parents)
    existing = next((path for path in candidates if path.is_file()), None)
    if existing is not None:
        return existing

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    config_root = Path(local_app_data) if local_app_data else Path.home() / ".hk-coretest"
    target = config_root / "HK-CoreTest" / "ai-model.env"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target
