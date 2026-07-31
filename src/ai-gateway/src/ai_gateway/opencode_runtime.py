"""Lifecycle and private configuration for the local OpenCode sidecar."""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Any, Callable, Mapping
from urllib.parse import quote
from urllib.request import Request, urlopen
from zipfile import ZipFile

from .model_client import ModelConfig, load_model_config


OPENCODE_VERSION = "1.18.10"
OPENCODE_WINDOWS_URL = (
    "https://github.com/anomalyco/opencode/releases/download/"
    f"v{OPENCODE_VERSION}/opencode-windows-x64.zip"
)
OPENCODE_WINDOWS_SHA256 = "b1d85ce5211bfefbc2b4940a19e1639fc75cb87ff82eb79806ffb84b01dd1482"


@dataclass(frozen=True)
class OpenCodeConfig:
    command: str = "opencode"
    host: str = "127.0.0.1"
    port: int = 4097
    health_timeout_seconds: float = 2

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def load_opencode_config(env: dict[str, str] | None = None) -> OpenCodeConfig:
    env = env or os.environ
    host = (env.get("OPENCODE_HOST") or "127.0.0.1").strip()
    if host != "127.0.0.1":
        raise ValueError("OPENCODE_HOST must be 127.0.0.1")
    try:
        port = int(env.get("OPENCODE_PORT") or 4097)
        timeout = float(env.get("OPENCODE_HEALTH_TIMEOUT_SECONDS") or 2)
    except ValueError as exc:
        raise ValueError("OpenCode port and timeout must be numeric") from exc
    if not 1 <= port <= 65535:
        raise ValueError("OPENCODE_PORT must be between 1 and 65535")
    if timeout <= 0:
        raise ValueError("OPENCODE_HEALTH_TIMEOUT_SECONDS must be positive")
    return OpenCodeConfig(
        command=(env.get("OPENCODE_COMMAND") or "auto").strip() or "auto",
        host=host,
        port=port,
        health_timeout_seconds=timeout,
    )


class OpenCodeRuntime:
    def __init__(
        self,
        *,
        config: OpenCodeConfig | None = None,
        model_config: ModelConfig | None = None,
        process_factory: Callable[..., Any] = subprocess.Popen,
        command_resolver: Callable[[str], str | None] = lambda command: resolve_opencode_command(command),
        urlopen: Callable[..., Any] = urlopen,
        password_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
    ) -> None:
        self.config = config or load_opencode_config()
        self.model_config = model_config or load_model_config()
        self._process_factory = process_factory
        self._command_resolver = command_resolver
        self._urlopen = urlopen
        self._password = password_factory()
        self._process: Any | None = None
        self._workspace: Path | None = None
        self._config_directory: TemporaryDirectory[str] | None = None
        self._error: str | None = None
        self._auth_configured = False
        self._sessions: dict[str, str] = {}
        self._session_lock = Lock()

    def start(self, workspace_root: str | Path) -> dict[str, Any]:
        workspace = _workspace_path(workspace_root)
        if self.running:
            if workspace != self._workspace:
                raise RuntimeError("OpenCode Runtime is already bound to another workspace")
            return self.status()

        command = self._command_resolver(self.config.command)
        if not command:
            self._error = "OpenCode executable was not found"
            raise RuntimeError(self._error)

        self._config_directory = TemporaryDirectory(prefix="geely-opencode-")
        config_path = Path(self._config_directory.name) / "opencode.json"
        config_path.write_text(
            json.dumps(_opencode_provider_config(self.model_config), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        environment = _minimal_process_environment(os.environ)
        environment["OPENCODE_SERVER_PASSWORD"] = self._password
        environment["OPENCODE_CONFIG"] = str(config_path)
        for name in ("DATA", "CONFIG", "CACHE", "STATE"):
            environment[f"XDG_{name}_HOME"] = str(
                Path(self._config_directory.name) / name.lower()
            )

        args = [
            command,
            "serve",
            "--hostname",
            self.config.host,
            "--port",
            str(self.config.port),
        ]
        try:
            self._process = self._process_factory(
                args,
                cwd=str(workspace),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self._error = "OpenCode process could not start"
            self._cleanup_config()
            raise RuntimeError(self._error) from exc
        self._workspace = workspace
        self._error = None
        self._auth_configured = False
        return self.status()

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def health(self) -> dict[str, Any]:
        if not self.running:
            return {"healthy": False, "version": None}
        request = Request(
            f"{self.config.base_url}/global/health",
            headers=self._authorization_headers(),
        )
        try:
            with self._urlopen(request, timeout=self.config.health_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._error = f"OpenCode health check failed: {exc}"
            return {"healthy": False, "version": None}
        healthy = payload.get("healthy") is True
        if healthy and self.model_config.is_configured and not self._auth_configured:
            healthy = self._configure_model_auth()
        if healthy:
            self._error = None
        return {
            "healthy": healthy,
            "version": str(payload.get("version")) if payload.get("version") else None,
        }

    def status(self, *, check_health: bool = False) -> dict[str, Any]:
        health = self.health() if check_health else {"healthy": False, "version": None}
        return {
            "installed": bool(self._command_resolver(self.config.command)),
            "running": self.running,
            "healthy": health["healthy"],
            "version": health["version"],
            "model_configured": self.model_config.is_configured,
            "error": self._error,
        }

    def stop(self) -> None:
        process = self._process
        self._process = None
        self._workspace = None
        self._auth_configured = False
        self._sessions.clear()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        self._cleanup_config()

    def prompt(
        self,
        host_session_id: str,
        question: str,
        *,
        system: str,
        history: list[dict[str, str]],
        new_session: bool = False,
    ) -> str:
        if not self.health()["healthy"]:
            raise RuntimeError(self._error or "OpenCode Runtime is unavailable")
        if new_session:
            self.release_session(host_session_id)
        with self._session_lock:
            session_id = self._sessions.get(host_session_id)
            created = session_id is None
            if session_id is None:
                session = self._request_json(
                    "POST",
                    "/session",
                    {"title": f"CoreTest {host_session_id}"},
                )
                session_id = str(session.get("id") or "")
                if not session_id:
                    raise RuntimeError("OpenCode did not create a session")
                self._sessions[host_session_id] = session_id

            prompt = question
            if created and history:
                prompt = (
                    "--- PREVIOUS CONVERSATION ---\n"
                    + "\n".join(
                        f"{item['role'].upper()}: {item['content']}" for item in history
                    )
                    + "\n--- END PREVIOUS CONVERSATION ---\n\n"
                    + question
                )
            result = self._request_json(
                "POST",
                f"/session/{quote(session_id, safe='')}/message",
                {
                    "system": system,
                    "parts": [{"type": "text", "text": prompt}],
                    "tools": {
                        "read": True,
                        "glob": True,
                        "grep": True,
                        "lsp": True,
                        "bash": False,
                        "edit": False,
                        "apply_patch": False,
                        "write": False,
                        "webfetch": False,
                        "websearch": False,
                        "task": False,
                    },
                },
                timeout=self.model_config.timeout_seconds + 30,
            )
        text_parts = [
            str(part.get("text") or "").strip()
            for part in result.get("parts", [])
            if isinstance(part, dict)
            and part.get("type") == "text"
            and part.get("ignored") is not True
            and str(part.get("text") or "").strip()
        ]
        if not text_parts:
            raise RuntimeError("OpenCode returned an empty response")
        return "\n\n".join(text_parts)

    def release_session(self, host_session_id: str) -> None:
        with self._session_lock:
            session_id = self._sessions.pop(host_session_id, None)
        if session_id is None or not self.running:
            return
        try:
            self._request_json("DELETE", f"/session/{quote(session_id, safe='')}")
        except RuntimeError:
            pass

    def release_sessions(self, host_session_id: str) -> None:
        prefix = f"{host_session_id}:"
        with self._session_lock:
            keys = [key for key in self._sessions if key.startswith(prefix)]
        for key in keys:
            self.release_session(key)

    def _cleanup_config(self) -> None:
        if self._config_directory is not None:
            self._config_directory.cleanup()
            self._config_directory = None

    def _configure_model_auth(self) -> bool:
        request = Request(
            f"{self.config.base_url}/auth/coretest",
            data=json.dumps(
                {"type": "api", "key": self.model_config.api_key},
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                **self._authorization_headers(),
                "Content-Type": "application/json",
            },
            method="PUT",
        )
        try:
            with self._urlopen(request, timeout=self.config.health_timeout_seconds) as response:
                response.read()
        except OSError:
            self._error = "OpenCode model authentication failed"
            return False
        self._auth_configured = True
        return True

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        request = Request(
            f"{self.config.base_url}{path}",
            data=(
                json.dumps(payload, ensure_ascii=False).encode("utf-8")
                if payload is not None
                else None
            ),
            headers={
                **self._authorization_headers(),
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with self._urlopen(
                request, timeout=timeout or self.config.health_timeout_seconds
            ) as response:
                raw = response.read()
        except OSError as exc:
            raise RuntimeError(f"OpenCode request failed: {method} {path}") from exc
        if not raw:
            return {}
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("OpenCode returned an invalid response") from exc
        if not isinstance(result, dict):
            raise RuntimeError("OpenCode returned an invalid response")
        return result

    def _authorization_headers(self) -> dict[str, str]:
        credentials = b64encode(f"opencode:{self._password}".encode()).decode()
        return {"Authorization": f"Basic {credentials}"}


def _workspace_path(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute() or not candidate.is_dir():
        raise ValueError("workspace must be an existing absolute directory")
    workspace = candidate.resolve()
    if workspace.parent == workspace:
        raise ValueError("workspace cannot be a filesystem root")
    return workspace


def resolve_opencode_command(command: str) -> str | None:
    if command.lower() != "auto":
        candidate = Path(command).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        return shutil.which(command)

    executable = "opencode.exe" if os.name == "nt" else "opencode"
    for candidate in (
        Path(sys.executable).resolve().parent / executable,
        Path(sys.executable).resolve().parent / "opencode" / executable,
        Path(__file__).resolve().parent / "bin" / executable,
    ):
        if candidate.is_file():
            return str(candidate.resolve())
    if installed := shutil.which("opencode"):
        return installed
    if os.name != "nt":
        return None

    local_app_data = os.getenv("LOCALAPPDATA")
    cache_root = (
        Path(local_app_data) / "HK-CoreTest" / "OpenCode"
        if local_app_data
        else Path.home() / ".cache" / "hk-coretest" / "opencode"
    )
    target = cache_root / OPENCODE_VERSION / "opencode.exe"
    if not target.is_file():
        with _install_lock:
            if not target.is_file():
                _install_opencode(target)
    return str(target.resolve())


def _install_opencode(
    target: Path,
    *,
    url: str = OPENCODE_WINDOWS_URL,
    expected_sha256: str = OPENCODE_WINDOWS_SHA256,
    opener: Callable[..., Any] = urlopen,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="coretest-opencode-download-") as directory:
        archive = Path(directory) / "opencode.zip"
        digest = sha256()
        try:
            with opener(url, timeout=120) as response, archive.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
        except OSError as exc:
            raise RuntimeError(
                f"OpenCode {OPENCODE_VERSION} download failed; check network access"
            ) from exc
        if digest.hexdigest().lower() != expected_sha256.lower():
            raise RuntimeError("OpenCode download failed SHA-256 verification")
        try:
            with ZipFile(archive) as bundle:
                staged = target.with_suffix(".tmp")
                with bundle.open("opencode.exe") as source, staged.open("wb") as output:
                    shutil.copyfileobj(source, output)
                staged.replace(target)
        except (KeyError, OSError) as exc:
            target.with_suffix(".tmp").unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise RuntimeError("OpenCode download archive is invalid") from exc


def _opencode_provider_config(model: ModelConfig) -> dict[str, Any]:
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "share": "disabled",
        "permission": {
            "read": "allow",
            "glob": "allow",
            "grep": "allow",
            "edit": "ask",
            "bash": "ask",
            "webfetch": "ask",
            "websearch": "ask",
            "external_directory": "deny",
        },
    }
    if not model.is_configured:
        return config
    provider_id = "coretest"
    model_id = model.model or ""
    config.update(
        {
            "model": f"{provider_id}/{model_id}",
            "small_model": f"{provider_id}/{model_id}",
            "provider": {
                provider_id: {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "CoreTest configured model",
                    "options": {
                        "baseURL": _openai_base_url(model.base_url or ""),
                    },
                    "models": {model_id: {"name": model_id}},
                }
            },
        }
    )
    return config


def _openai_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def _minimal_process_environment(source: Mapping[str, str]) -> dict[str, str]:
    allowed = {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "NUMBER_OF_PROCESSORS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "SHELL",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TERM",
        "TMP",
        "TMPDIR",
        "USER",
        "USERPROFILE",
        "WINDIR",
    }
    return {name: value for name, value in source.items() if name.upper() in allowed}


_runtime: OpenCodeRuntime | None = None
_install_lock = Lock()


def get_opencode_runtime() -> OpenCodeRuntime:
    global _runtime
    if _runtime is None:
        _runtime = OpenCodeRuntime()
    return _runtime


def reset_opencode_runtime() -> None:
    global _runtime
    if _runtime is not None:
        _runtime.stop()
    _runtime = None
