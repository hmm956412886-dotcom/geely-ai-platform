"""Qt-native Gateway process and HTTP client."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any, Callable
from uuid import uuid4

from PySide6.QtCore import QByteArray, QProcess, QProcessEnvironment, QTimer, QUrl
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
        self._poll = QTimer(parent)
        self._poll.setInterval(350)
        self._poll.timeout.connect(self._check_health)

    @property
    def copilot_url(self) -> QUrl:
        token = os.getenv("AI_GATEWAY_ACCESS_TOKEN", "").strip()
        url = f"{self.base_url}/copilot-shell/?host_session_id={self.session_id}"
        if token:
            url += f"#access_token={QUrl.toPercentEncoding(token).data().decode()}"
        return QUrl(url)

    def on_ready(self, callback: Callable[[], None]) -> None:
        self._ready_callbacks.append(callback)

    def on_error(self, callback: Callable[[str], None]) -> None:
        self._error_callbacks.append(callback)

    def start(self) -> None:
        if self.ready:
            return
        gateway_src = _gateway_src()
        if gateway_src is None:
            self._fail("未找到 AI Gateway。请设置 CORETEST_AI_PLATFORM_ROOT。")
            return
        environment = QProcessEnvironment.systemEnvironment()
        for name, value in _load_env_values(gateway_src.parents[2] / ".env").items():
            if value and not environment.contains(name):
                environment.insert(name, value)
        current = environment.value("PYTHONPATH")
        environment.insert("PYTHONPATH", f"{gateway_src}{os.pathsep}{current}" if current else str(gateway_src))
        environment.insert("PYTHONUNBUFFERED", "1")
        self.process.setProcessEnvironment(environment)
        self.process.start(sys.executable, ["-m", "ai_gateway.server", "--port", "8765"])
        self._attempts = 0
        self._poll.start()

    def retry(self) -> None:
        self.stop_process()
        self.ready = False
        self.start()

    def publish(self, context: dict[str, Any], snapshot: dict[str, Any]) -> None:
        self.request("POST", "/api/v1/host/context", context)
        self.request("POST", "/api/v1/host/snapshot", snapshot, privileged=True)

    def release(self) -> None:
        if self.ready:
            self.request("DELETE", "/api/v1/host/session", privileged=True)
        self.stop_process()

    def stop_process(self) -> None:
        self._poll.stop()
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
    ) -> None:
        separator = "&" if "?" in path else "?"
        request = QNetworkRequest(QUrl(f"{self.base_url}{path}{separator}host_session_id={self.session_id}"))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        token_name = "AI_GATEWAY_HOST_TOKEN" if privileged else "AI_GATEWAY_ACCESS_TOKEN"
        token = os.getenv(token_name, "").strip()
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
        reply.deleteLater()
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
    candidates = [Path(configured)] if configured else []
    candidates.extend(Path(__file__).resolve().parents)
    for root in candidates:
        source = root / "src" / "ai-gateway" / "src"
        if (source / "ai_gateway" / "server.py").is_file():
            return source
    return None


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
