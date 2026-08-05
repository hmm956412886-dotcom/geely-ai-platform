"""Lifecycle and private configuration for the local OpenCode sidecar."""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic, sleep
from typing import Any, Callable, Iterator, Mapping
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen
from zipfile import ZipFile

from .host_bridge import HostBridgeConfig
from .model_client import ModelConfig, load_model_config


OPENCODE_VERSION = "1.18.10"
OPENCODE_WINDOWS_URL = (
    "https://github.com/anomalyco/opencode/releases/download/"
    f"v{OPENCODE_VERSION}/opencode-windows-x64.zip"
)
OPENCODE_WINDOWS_SHA256 = "b1d85ce5211bfefbc2b4940a19e1639fc75cb87ff82eb79806ffb84b01dd1482"
OPENCODE_WINDOWS_EXE_SHA256 = "8cc6228ced60be31b2b3408b5711f6922bc6654fba9ce63fed29264f2a4a01dd"
PROVIDER_TEST_TIMEOUT_SECONDS = 30


_NATIVE_UI_ROUTES: dict[str, tuple[str, ...]] = {
    "GET": (
        r"/global/health",
        r"/global/event",
        r"/event",
        r"/experimental/resource",
        r"/(?:agent|command|config|config/providers|formatter|lsp|mcp|permission|provider|provider/auth|question|skill)",
        r"/(?:file|file/content|file/status|find|find/file|find/symbol)",
        r"/path",
        r"/project(?:/current|/[^/]+/directories)?",
        r"/session(?:/status|/[^/]+(?:/(?:children|diff|message(?:/[^/]+)?|todo))?)?",
        r"/vcs(?:/status|/diff|/diff/raw)?",
    ),
    "POST": (
        r"/log",
        r"/permission/[^/]+/reply",
        r"/question/[^/]+/(?:reply|reject)",
        r"/session",
        r"/session/[^/]+/(?:abort|command|fork|init|prompt_async|revert|summarize|unrevert)",
    ),
    "PUT": (r"/auth/[A-Za-z0-9][A-Za-z0-9_-]{0,63}",),
    "PATCH": (r"/config", r"/session/[^/]+"),
    "DELETE": (
        r"/auth/[A-Za-z0-9][A-Za-z0-9_-]{0,63}",
        r"/session/[^/]+",
    ),
}


@dataclass(frozen=True)
class OpenCodeNativeResponse:
    status: int
    body: bytes = b""
    content_type: str = "application/octet-stream"
    headers: Mapping[str, str] | None = None
    stream: Iterator[bytes] | None = None


@dataclass(frozen=True)
class OpenCodeConfig:
    command: str = "opencode"
    host: str = "127.0.0.1"
    port: int = 4097
    health_timeout_seconds: float = 2
    stream_idle_timeout_seconds: float = 300
    turn_timeout_seconds: float = 1800
    state_root: Path | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def load_opencode_config(env: dict[str, str] | None = None) -> OpenCodeConfig:
    env = env or os.environ
    host = (env.get("OPENCODE_HOST") or "127.0.0.1").strip()
    if host != "127.0.0.1":
        raise ValueError("OPENCODE_HOST must be 127.0.0.1")
    try:
        configured_port = str(env.get("OPENCODE_PORT") or "").strip()
        port = int(configured_port) if configured_port else _available_loopback_port(host)
        timeout = float(env.get("OPENCODE_HEALTH_TIMEOUT_SECONDS") or 2)
        stream_idle_timeout = float(
            env.get("OPENCODE_STREAM_IDLE_TIMEOUT_SECONDS") or 300
        )
        turn_timeout = float(env.get("OPENCODE_TURN_TIMEOUT_SECONDS") or 1800)
    except ValueError as exc:
        raise ValueError("OpenCode port and timeout must be numeric") from exc
    if not 1 <= port <= 65535:
        raise ValueError("OPENCODE_PORT must be between 1 and 65535")
    if timeout <= 0:
        raise ValueError("OPENCODE_HEALTH_TIMEOUT_SECONDS must be positive")
    if stream_idle_timeout <= 0:
        raise ValueError("OpenCode stream idle timeout must be positive")
    if turn_timeout < stream_idle_timeout:
        raise ValueError("OpenCode turn timeout must be at least the stream idle timeout")
    return OpenCodeConfig(
        command=(env.get("OPENCODE_COMMAND") or "auto").strip() or "auto",
        host=host,
        port=port,
        health_timeout_seconds=timeout,
        stream_idle_timeout_seconds=stream_idle_timeout,
        turn_timeout_seconds=turn_timeout,
        state_root=_opencode_state_root(env),
    )


def _available_loopback_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        return int(listener.getsockname()[1])


class OpenCodeRuntime:
    def __init__(
        self,
        *,
        config: OpenCodeConfig | None = None,
        model_config: ModelConfig | None = None,
        process_factory: Callable[..., Any] = subprocess.Popen,
        command_resolver: Callable[[str], str | None] | None = None,
        command_probe: Callable[[str], str | None] | None = None,
        urlopen: Callable[..., Any] = urlopen,
        password_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
    ) -> None:
        self.config = config or load_opencode_config()
        self.model_config = model_config or load_model_config()
        self._process_factory = process_factory
        self._command_resolver = command_resolver or resolve_opencode_command
        self._command_probe = command_probe or (
            command_resolver if command_resolver is not None else find_opencode_command
        )
        self._urlopen = urlopen
        self._password = password_factory()
        self._process: Any | None = None
        self._source_workspace: Path | None = None
        self._workspace: Path | None = None
        self._host_bridge: HostBridgeConfig | None = None
        self._config_path: Path | None = None
        self._error: str | None = None
        self._auth_configured = False
        self._sessions: dict[str, str] = {}
        self._last_user_messages: dict[str, str] = {}
        self._pending_permissions: dict[str, dict[str, dict[str, Any]]] = {}
        self._rejected_sessions: set[str] = set()
        self._part_types: dict[tuple[str, str], str] = {}
        self._session_lock = Lock()

    def start(
        self,
        workspace_root: str | Path,
        *,
        host_bridge: HostBridgeConfig | None = None,
    ) -> dict[str, Any]:
        source_workspace = _workspace_path(workspace_root)
        if self.running:
            if source_workspace != self._source_workspace:
                raise RuntimeError("CoreTest Agent Runtime is already bound to another workspace")
            if host_bridge == self._host_bridge:
                return self.status()
            self.stop()
        if self._process is not None:
            self.stop()

        command = self._command_resolver(self.config.command)
        if not command:
            self._error = "CoreTest Agent Runtime is not installed"
            raise RuntimeError(self._error)

        state_root = (self.config.state_root or _opencode_state_root(os.environ)).resolve()
        config_path = self._prepare_config(state_root)
        self._config_path = config_path
        workspace = source_workspace
        environment = _minimal_process_environment(os.environ)
        environment["OPENCODE_SERVER_PASSWORD"] = self._password
        environment["OPENCODE_CONFIG"] = str(config_path)
        for name in ("DATA", "CONFIG", "CACHE", "STATE"):
            path = state_root / name.lower()
            path.mkdir(parents=True, exist_ok=True)
            environment[f"XDG_{name}_HOME"] = str(path)
        if host_bridge is not None:
            cli_directory = _prepare_host_cli(state_root)
            environment["CORETEST_HOST_BRIDGE_URL"] = host_bridge.url
            environment["CORETEST_HOST_BRIDGE_TOKEN"] = host_bridge.token
            environment["PATH"] = (
                f"{cli_directory}{os.pathsep}{environment.get('PATH', '')}"
            ).rstrip(os.pathsep)

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
            self._error = "CoreTest Agent Runtime could not start"
            raise RuntimeError(self._error) from exc
        self._source_workspace = source_workspace
        self._workspace = workspace
        self._host_bridge = host_bridge
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
            self._error = f"CoreTest Agent Runtime health check failed: {exc}"
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
            "installed": bool(self._command_probe(self.config.command)),
            "running": self.running,
            "healthy": health["healthy"],
            "version": health["version"],
            "model_configured": self._active_model() is not None,
            "error": self._error,
        }

    def stop(self) -> None:
        process = self._process
        self._process = None
        self._source_workspace = None
        self._workspace = None
        self._host_bridge = None
        self._auth_configured = False
        with self._session_lock:
            self._sessions.clear()
            self._last_user_messages.clear()
            self._rejected_sessions.clear()
            self._part_types.clear()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)

    def prompt(
        self,
        host_session_id: str,
        question: str,
        *,
        system: str,
        history: list[dict[str, str]],
        new_session: bool = False,
    ) -> str:
        self._require_healthy()
        if new_session:
            self.release_session(host_session_id)
        with self._session_lock:
            self._rejected_sessions.discard(host_session_id)
            session_id = self._sessions.get(host_session_id)
            created = session_id is None
            if session_id is None:
                session = self._request_json(
                    "POST",
                    "/session",
                    {
                        "title": f"CoreTest {host_session_id}",
                        "permission": _session_permissions(),
                    },
                )
                session_id = str(session.get("id") or "")
                if not session_id:
                    raise RuntimeError("CoreTest Agent did not create a session")
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
        try:
            result = self._request_json(
                "POST",
                f"/session/{quote(session_id, safe='')}/message",
                {
                    "model": self._message_model(),
                    "system": system,
                    "parts": [{"type": "text", "text": prompt}],
                },
                timeout=max(self.model_config.timeout_seconds + 30, 600),
            )
        except RuntimeError:
            if self._take_rejection(host_session_id):
                return "已拒绝本次操作，CoreTest Agent 未执行该工具。"
            raise
        text_parts = [
            str(part.get("text") or "").strip()
            for part in result.get("parts", [])
            if isinstance(part, dict)
            and part.get("type") == "text"
            and part.get("ignored") is not True
            and str(part.get("text") or "").strip()
        ]
        if not text_parts:
            if self._take_rejection(host_session_id):
                return "已拒绝本次操作，CoreTest Agent 未执行该工具。"
            raise RuntimeError("CoreTest Agent returned an empty response")
        info = result.get("info")
        if isinstance(info, dict) and str(info.get("parentID") or ""):
            with self._session_lock:
                self._last_user_messages[host_session_id] = str(info["parentID"])
        with self._session_lock:
            self._rejected_sessions.discard(host_session_id)
        return "\n\n".join(text_parts)

    def stream_prompt(
        self,
        host_session_id: str,
        question: str,
        *,
        system: str,
        history: list[dict[str, str]],
        new_session: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Send an async OpenCode prompt and yield sanitized SSE events."""
        self._require_healthy()
        if new_session:
            self.release_session(host_session_id)
        session_id, created = self._ensure_session(host_session_id)
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
        directory = quote(str(self._workspace or ""), safe="")
        response = self._open_event_stream()
        try:
            self._request_value(
                "POST",
                f"/session/{quote(session_id, safe='')}/prompt_async?directory={directory}",
                {
                    "model": self._message_model(),
                    "system": system,
                    "parts": [{"type": "text", "text": prompt}],
                },
            )
        except RuntimeError:
            response.close()
            if self._take_rejection(host_session_id):
                yield {"type": "error", "message": "本次操作已拒绝，CoreTest Agent 未执行该工具。"}
                return
            raise
        text_parts: list[str] = []
        current_segment: str | None = None
        completed = False
        failed = False
        try:
            yield {"type": "started"}
            for event in self._read_events(response, session_id):
                if event.get("type") == "text_delta":
                    delta = str(event.get("delta") or "")
                    segment = str(event.get("segment_id") or "") or None
                    if current_segment is not None and segment != current_segment:
                        delta = "\n\n" + delta.lstrip()
                        event = {**event, "delta": delta}
                    current_segment = segment
                    text_parts.append(delta)
                if event.get("type") == "permission" and isinstance(event.get("permission"), dict):
                    permission = event["permission"]
                    permission_id = str(permission.get("id") or "")
                    if permission_id:
                        self._reject_unexpected_permission(host_session_id, permission_id)
                    continue
                if event.get("type") == "idle":
                    completed = True
                if event.get("type") == "error":
                    failed = True
                yield event
                if failed:
                    return
        finally:
            response.close()
            if failed or not completed:
                self._abandon_session(host_session_id)
        answer = "".join(text_parts).strip()
        if answer:
            yield {"type": "completed", "answer": answer}

    def _ensure_session(self, host_session_id: str) -> tuple[str, bool]:
        with self._session_lock:
            session_id = self._sessions.get(host_session_id)
            if session_id is not None:
                return session_id, False
            session = self._request_json(
                "POST",
                "/session",
                {"title": f"CoreTest {host_session_id}", "permission": _session_permissions()},
            )
            session_id = str(session.get("id") or "")
            if not session_id:
                raise RuntimeError("CoreTest Agent did not create a session")
            self._sessions[host_session_id] = session_id
            return session_id, True

    def pending_permissions(self, host_session_id: str) -> list[dict[str, Any]]:
        session_id = self._session_id(host_session_id)
        if session_id is None:
            return []
        directory = quote(str(self._workspace or ""), safe="")
        try:
            result = self._request_value("GET", f"/permission?directory={directory}")
        except RuntimeError:
            with self._session_lock:
                return list(self._pending_permissions.get(host_session_id, {}).values())
        if not isinstance(result, list):
            raise RuntimeError("CoreTest Agent returned invalid permission data")
        permissions = [
            self._public_permission(item)
            for item in result
            if isinstance(item, dict) and item.get("sessionID") == session_id
        ]
        for permission in permissions:
            if permission["id"]:
                self._reject_unexpected_permission(host_session_id, permission["id"])
        return []

    def activity(self, host_session_id: str) -> list[dict[str, str]]:
        session_id = self._session_id(host_session_id)
        if session_id is None:
            return []
        directory = quote(str(self._workspace or ""), safe="")
        result = self._request_value(
            "GET",
            f"/session/{quote(session_id, safe='')}/message?directory={directory}",
        )
        if not isinstance(result, list):
            raise RuntimeError("CoreTest Agent returned invalid activity data")
        steps: list[dict[str, str]] = []
        for message in result:
            if not isinstance(message, dict):
                continue
            for part in message.get("parts", []):
                if not isinstance(part, dict) or part.get("type") != "tool":
                    continue
                state = part.get("state")
                if not isinstance(state, dict):
                    continue
                tool = str(part.get("tool") or "tool")
                title = str(state.get("title") or tool)
                output = str(state.get("output") or "")
                steps.append(
                    {
                        "id": str(part.get("id") or part.get("callID") or ""),
                        "tool": tool,
                        "status": str(state.get("status") or "pending"),
                        "title": self._public_text(title, 300),
                        "output": self._public_text(output, 1000),
                    }
                )
        return steps[-20:]

    def _open_event_stream(self) -> Any:
        directory = quote(str(self._workspace or ""), safe="")
        request = Request(
            f"{self.config.base_url}/event?directory={directory}",
            headers={
                **self._authorization_headers(),
                "Accept": "text/event-stream",
            },
        )
        try:
            return self._urlopen(
                request, timeout=self.config.stream_idle_timeout_seconds
            )
        except OSError as exc:
            raise RuntimeError("CoreTest Agent event stream failed") from exc

    def _read_events(
        self, response: Any, session_id: str
    ) -> Iterator[dict[str, Any]]:
        started = monotonic()
        last_progress = started
        try:
            while True:
                try:
                    raw_line = response.readline()
                except TimeoutError as exc:
                    raise RuntimeError(
                        "CoreTest Agent event stream made no progress for too long"
                    ) from exc
                except OSError as exc:
                    raise RuntimeError("CoreTest Agent event stream disconnected") from exc
                if not raw_line:
                    raise RuntimeError("CoreTest Agent event stream disconnected before session idle")
                now = monotonic()
                if now - started > self.config.turn_timeout_seconds:
                    raise RuntimeError("CoreTest Agent turn exceeded the maximum duration")
                if now - last_progress > self.config.stream_idle_timeout_seconds:
                    raise RuntimeError("CoreTest Agent event stream made no progress for too long")
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                public = self._public_event(event, session_id)
                if public is not None:
                    last_progress = now
                    yield public
                if public and public.get("type") in {"idle", "error"}:
                    return
        finally:
            response.close()

    def _public_event(
        self, event: dict[str, Any], session_id: str
    ) -> dict[str, Any] | None:
        properties = event.get("properties")
        if not isinstance(properties, dict) or properties.get("sessionID") != session_id:
            return None
        event_type = str(event.get("type") or "")
        if event_type == "message.updated":
            info = properties.get("info")
            if isinstance(info, dict) and info.get("role") == "assistant" and info.get("parentID"):
                with self._session_lock:
                    for host_session_id, candidate in self._sessions.items():
                        if candidate == session_id:
                            self._last_user_messages[host_session_id] = str(info["parentID"])
                            break
            return None
        if event_type == "message.part.delta":
            if properties.get("field") not in {None, "text"}:
                return None
            delta = str(properties.get("delta") or "")
            if not delta:
                return None
            message_id = _public_event_id(properties.get("messageID"))
            part_id = _public_event_id(properties.get("partID"))
            segment_id = ":".join(item for item in (message_id, part_id) if item)
            part_type = self._part_types.get((session_id, part_id), "text")
            public = {
                "type": "reasoning_delta" if part_type == "reasoning" else "text_delta",
                "delta": delta,
            }
            if segment_id:
                public["segment_id"] = segment_id
            return public
        if event_type == "message.part.updated":
            part = properties.get("part")
            if not isinstance(part, dict):
                return None
            part_id = _public_event_id(part.get("id"))
            part_type = str(part.get("type") or "")
            if part_id and part_type in {"text", "reasoning"}:
                self._part_types[(session_id, part_id)] = part_type
                return None
            if part_type == "step-start":
                return {
                    "type": "step",
                    "id": part_id,
                    "status": "running",
                    "title": "开始执行",
                }
            if part_type == "step-finish":
                return {
                    "type": "step",
                    "id": part_id,
                    "status": "completed",
                    "title": self._public_text(str(part.get("reason") or "执行完成"), 300),
                }
            if part_type == "retry":
                error = part.get("error") if isinstance(part.get("error"), dict) else {}
                return {
                    "type": "retry",
                    "attempt": max(0, int(part.get("attempt") or 0)),
                    "message": self._public_text(str(error.get("message") or "模型调用重试"), 300),
                }
            if part_type == "patch":
                files = part.get("files") if isinstance(part.get("files"), list) else []
                return {
                    "type": "patch",
                    "files": [
                        file
                        for value in files[:20]
                        if (file := self._public_file(str(value))) is not None
                    ],
                }
            if part_type != "tool":
                return None
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            return {
                "type": "tool",
                "id": str(part.get("id") or part.get("callID") or ""),
                "tool": str(part.get("tool") or "tool"),
                "status": str(state.get("status") or "pending"),
                "title": self._public_text(str(state.get("title") or part.get("tool") or "tool"), 300),
                "output": self._public_text(str(state.get("output") or ""), 1000),
            }
        if event_type == "todo.updated":
            todos = properties.get("todos")
            if not isinstance(todos, list):
                return None
            return {
                "type": "todo",
                "todos": [
                    {
                        "content": self._public_text(str(item.get("content") or ""), 300),
                        "status": str(item.get("status") or "pending"),
                        "priority": str(item.get("priority") or "medium"),
                    }
                    for item in todos[:20]
                    if isinstance(item, dict) and str(item.get("content") or "").strip()
                ],
            }
        if event_type in {"permission.asked", "permission.asked.v2"}:
            return {"type": "permission", "permission": self._public_permission(properties)}
        if event_type == "session.idle":
            return {"type": "idle"}
        if event_type == "session.error":
            error = properties.get("error")
            if isinstance(error, dict):
                data = error.get("data")
                message = error.get("message") or (
                    data.get("message") if isinstance(data, dict) else None
                )
            else:
                message = str(error or "")
            message = message or "CoreTest Agent session failed"
            return {"type": "error", "message": self._public_text(str(message), 500)}
        return None

    def diff(self, host_session_id: str) -> dict[str, Any]:
        session_id, message_id = self._session_and_message_id(host_session_id)
        if session_id is None or message_id is None:
            return {
                "files": [],
                "revert_available": False,
                "revert_reason": "no_turn",
            }
        directory = quote(str(self._workspace or ""), safe="")
        result = self._request_value(
            "GET",
            f"/session/{quote(session_id, safe='')}/diff"
            f"?directory={directory}&messageID={quote(message_id, safe='')}",
        )
        if not isinstance(result, list):
            raise RuntimeError("CoreTest Agent returned invalid diff data")
        files: list[dict[str, Any]] = []
        remaining = 40_000
        for item in result[:20]:
            if not isinstance(item, dict) or remaining <= 0:
                continue
            path = self._public_file(str(item.get("file") or ""))
            if path is None:
                continue
            raw_patch = str(item.get("patch") or "")
            limit = min(12_000, remaining)
            patch = self._public_patch(raw_patch[:limit])
            remaining -= len(patch)
            status = str(item.get("status") or "modified")
            if status not in {"added", "deleted", "modified"}:
                status = "modified"
            files.append(
                {
                    "path": path,
                    "status": status,
                    "additions": max(0, int(item.get("additions") or 0)),
                    "deletions": max(0, int(item.get("deletions") or 0)),
                    "patch": patch,
                    "truncated": len(raw_patch) > limit,
                }
            )
        if files:
            return {
                "files": files,
                "revert_available": True,
                "revert_reason": None,
            }
        reason = (
            "workspace_has_no_git_baseline"
            if self._turn_has_completed_write(session_id, message_id, directory)
            else "no_file_changes"
        )
        return {
            "files": [],
            "revert_available": False,
            "revert_reason": reason,
        }

    def _turn_has_completed_write(
        self, session_id: str, message_id: str, directory: str
    ) -> bool:
        result = self._request_value(
            "GET",
            f"/session/{quote(session_id, safe='')}/message?directory={directory}",
        )
        if not isinstance(result, list):
            raise RuntimeError("CoreTest Agent returned invalid activity data")
        for message in result:
            if not isinstance(message, dict):
                continue
            info = message.get("info")
            if not isinstance(info, dict) or info.get("parentID") != message_id:
                continue
            for part in message.get("parts", []):
                if not isinstance(part, dict) or part.get("type") != "tool":
                    continue
                state = part.get("state")
                if (
                    part.get("tool") in {"edit", "write", "apply_patch"}
                    and isinstance(state, dict)
                    and state.get("status") == "completed"
                ):
                    return True
        return False

    def revert(self, host_session_id: str) -> bool:
        if not self.diff(host_session_id)["revert_available"]:
            return False
        session_id, message_id = self._session_and_message_id(host_session_id)
        if session_id is None or message_id is None:
            return False
        self._request_value(
            "POST",
            f"/session/{quote(session_id, safe='')}/revert"
            f"?directory={quote(str(self._workspace or ''), safe='')}",
            {"messageID": message_id},
        )
        with self._session_lock:
            self._last_user_messages.pop(host_session_id, None)
        return True

    def reply_permission(
        self, host_session_id: str, request_id: str, reply: str
    ) -> None:
        if reply not in {"once", "reject"}:
            raise ValueError("permission reply must be once or reject")
        with self._session_lock:
            pending = set(self._pending_permissions.get(host_session_id, {}))
        if request_id not in pending:
            pending = {item["id"] for item in self.pending_permissions(host_session_id)}
        if request_id not in pending:
            raise ValueError("permission request is not pending for this conversation")
        with self._session_lock:
            self._rejected_sessions.add(host_session_id)
        self._request_value(
            "POST",
            f"/permission/{quote(request_id, safe='')}/reply?directory={quote(str(self._workspace or ''), safe='')}",
            {"reply": "reject"},
        )
        with self._session_lock:
            self._pending_permissions.get(host_session_id, {}).pop(request_id, None)

    def _reject_unexpected_permission(
        self, host_session_id: str, request_id: str
    ) -> None:
        with self._session_lock:
            self._rejected_sessions.add(host_session_id)
        self._request_value(
            "POST",
            f"/permission/{quote(request_id, safe='')}/reply"
            f"?directory={quote(str(self._workspace or ''), safe='')}",
            {"reply": "reject"},
        )

    def abort(self, host_session_id: str) -> bool:
        session_id = self._session_id(host_session_id)
        if session_id is None:
            return False
        self._request_value(
            "POST",
            f"/session/{quote(session_id, safe='')}/abort?directory={quote(str(self._workspace or ''), safe='')}",
            {},
        )
        return True

    def _abandon_session(self, host_session_id: str) -> None:
        try:
            self.abort(host_session_id)
        except RuntimeError:
            pass
        self.release_session(host_session_id)

    def _session_id(self, host_session_id: str) -> str | None:
        with self._session_lock:
            return self._sessions.get(host_session_id)

    def _session_and_message_id(
        self, host_session_id: str
    ) -> tuple[str | None, str | None]:
        with self._session_lock:
            return (
                self._sessions.get(host_session_id),
                self._last_user_messages.get(host_session_id),
            )

    def _take_rejection(self, host_session_id: str) -> bool:
        with self._session_lock:
            rejected = host_session_id in self._rejected_sessions
            self._rejected_sessions.discard(host_session_id)
            return rejected

    def _public_permission(self, item: dict[str, Any]) -> dict[str, Any]:
        resources = item.get("patterns") or item.get("resources") or []
        if not isinstance(resources, list):
            resources = []
        return {
            "id": str(item.get("id") or ""),
            "permission": str(item.get("permission") or item.get("action") or "tool"),
            "resources": [
                self._public_resource(str(resource))
                for resource in resources[:10]
                if str(resource).strip()
            ],
        }

    def _public_resource(self, value: str) -> str:
        resource = self._public_text(value, 500)
        if resource == ".":
            return resource
        if resource.startswith(("./", ".\\")):
            relative = resource[1:].lstrip("/\\")
            return relative or "."
        return resource

    def _public_file(self, value: str) -> str | None:
        if self._workspace is None or not value.strip():
            return None
        candidate = Path(value)
        try:
            relative = (
                candidate.resolve().relative_to(self._workspace)
                if candidate.is_absolute()
                else (self._workspace / candidate).resolve().relative_to(self._workspace)
            )
        except (OSError, ValueError):
            return None
        return relative.as_posix()

    def _public_patch(self, value: str) -> str:
        patch = self._replace_workspace_path(value)
        return re.sub(
            r"(?i)[A-Z]:[\\/][^\s\r\n]+",
            "[工作区外路径已隐藏]",
            patch,
        )

    def _public_text(self, value: str, limit: int) -> str:
        resource = self._replace_workspace_path(value.strip()[:limit])
        if resource == ".." or resource.startswith(("../", "..\\")):
            return "[工作区外路径已隐藏]"
        if Path(resource).is_absolute() or re.search(r"[A-Za-z]:[\\/]", resource):
            return "[工作区外路径已隐藏]"
        return resource

    def _replace_workspace_path(self, value: str) -> str:
        normalized = value.replace("\\", "/")
        if self._workspace is None:
            return normalized
        workspace = str(self._workspace).replace("\\", "/")
        candidates = [workspace]
        if re.match(r"^[A-Za-z]:/", workspace):
            without_drive = workspace[3:]
            candidates.extend([f"/{without_drive}", without_drive])
        for candidate in candidates:
            position = normalized.lower().find(candidate.lower())
            if position >= 0:
                return normalized[:position] + "." + normalized[position + len(candidate):]
        return normalized

    def release_session(self, host_session_id: str) -> None:
        with self._session_lock:
            session_id = self._sessions.pop(host_session_id, None)
            self._last_user_messages.pop(host_session_id, None)
            self._pending_permissions.pop(host_session_id, None)
            self._rejected_sessions.discard(host_session_id)
            if session_id is not None:
                self._part_types = {
                    key: value for key, value in self._part_types.items() if key[0] != session_id
                }
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

    def providers(self) -> dict[str, Any]:
        self._require_healthy()
        config = self._request_json("GET", "/config")
        provider_state = self._request_json(
            "GET",
            "/provider",
            timeout=max(30.0, self.config.health_timeout_seconds * 10),
        )
        return _public_provider_catalog(config, provider_state)

    def save_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider_id, provider, api_key, activate = _provider_update(payload)
        self._require_healthy()
        config = self._request_json("GET", "/config")
        disabled = [
            item
            for item in config.get("disabled_providers", [])
            if isinstance(item, str) and item != provider_id
        ]
        if api_key:
            self._request_value(
                "PUT",
                f"/auth/{quote(provider_id, safe='')}",
                {"type": "api", "key": api_key},
            )
        update: dict[str, Any] = {
            "provider": {provider_id: provider},
            "disabled_providers": disabled,
        }
        if activate:
            model_id = next(iter(provider["models"]))
            update.update(
                {
                    "model": f"{provider_id}/{model_id}",
                    "small_model": f"{provider_id}/{model_id}",
                }
            )
        self._request_value("PATCH", "/config", update)
        return self.providers()

    def activate_provider(self, provider_id: str, model_id: str) -> dict[str, Any]:
        provider_id = _provider_id(provider_id)
        model_id = _model_id(model_id)
        catalog = self.providers()
        provider = next(
            (item for item in catalog["providers"] if item["id"] == provider_id), None
        )
        if provider is None or model_id not in {item["id"] for item in provider["models"]}:
            raise ValueError("provider or model does not exist")
        self._request_value(
            "PATCH",
            "/config",
            {
                "model": f"{provider_id}/{model_id}",
                "small_model": f"{provider_id}/{model_id}",
            },
        )
        return self.providers()

    def delete_provider(self, provider_id: str) -> dict[str, Any]:
        provider_id = _provider_id(provider_id)
        catalog = self.providers()
        if not any(item["id"] == provider_id for item in catalog["providers"]):
            raise ValueError("provider does not exist")
        config = self._request_json("GET", "/config")
        self._request_value("DELETE", f"/auth/{quote(provider_id, safe='')}")
        disabled = list(
            dict.fromkeys(
                [
                    *[
                        item
                        for item in config.get("disabled_providers", [])
                        if isinstance(item, str)
                    ],
                    provider_id,
                ]
            )
        )
        update: dict[str, Any] = {"disabled_providers": disabled}
        fallback = next(
            (item for item in catalog["providers"] if item["id"] != provider_id), None
        )
        if catalog.get("active_provider_id") == provider_id and fallback:
            model_id = fallback["models"][0]["id"]
            update.update(
                {
                    "model": f"{fallback['id']}/{model_id}",
                    "small_model": f"{fallback['id']}/{model_id}",
                }
            )
        self._request_value("PATCH", "/config", update)
        return self.providers()

    def test_provider(self, provider_id: str, model_id: str) -> dict[str, Any]:
        provider_id = _provider_id(provider_id)
        model_id = _model_id(model_id)
        catalog = self.providers()
        provider = next(
            (item for item in catalog["providers"] if item["id"] == provider_id), None
        )
        if provider is None or model_id not in {item["id"] for item in provider["models"]}:
            raise ValueError("provider or model does not exist")
        probe_file = _provider_probe_file(self._workspace)
        if probe_file is None or self._workspace is None:
            raise RuntimeError("workspace has no small text file for the read-only compatibility check")
        probe_path = probe_file.relative_to(self._workspace).as_posix()
        session = self._request_json(
            "POST",
            "/session",
            {"title": "CoreTest provider compatibility check", "permission": _session_permissions()},
        )
        session_id = str(session.get("id") or "")
        if not session_id:
            raise RuntimeError("CoreTest Agent did not create a compatibility session")
        try:
            result = self._request_json(
                "POST",
                f"/session/{quote(session_id, safe='')}/message",
                {
                    "model": {"providerID": provider_id, "modelID": model_id},
                    "system": (
                        "This is a read-only Agent compatibility check. "
                        "You must use the read tool once before replying."
                    ),
                    "parts": [
                        {
                            "type": "text",
                            "text": (
                                f"Use read on {json.dumps(probe_path)}, "
                                "then reply exactly OK."
                            ),
                        }
                    ],
                },
                timeout=PROVIDER_TEST_TIMEOUT_SECONDS,
            )
            parts = result.get("parts")
            if not isinstance(parts, list) or not parts:
                raise RuntimeError("model returned no compatible CoreTest Agent message parts")
            directory = quote(str(self._workspace or ""), safe="")
            messages = self._request_value(
                "GET",
                f"/session/{quote(session_id, safe='')}/message?directory={directory}",
                timeout=PROVIDER_TEST_TIMEOUT_SECONDS,
            )
            message_list = messages if isinstance(messages, list) else []
            tool_used = any(
                isinstance(part, dict)
                and part.get("type") == "tool"
                and isinstance(part.get("state"), dict)
                and part["state"].get("status") == "completed"
                for message in message_list if isinstance(message, dict)
                for part in message.get("parts", []) if isinstance(message.get("parts"), list)
            )
            if not tool_used:
                raise RuntimeError("model did not complete a CoreTest Agent tool call")
        finally:
            self._request_value("DELETE", f"/session/{quote(session_id, safe='')}")
        return {"ok": True, "provider_id": provider_id, "model_id": model_id}

    def _prepare_config(self, state_root: Path) -> Path:
        config_path = state_root / "config" / "opencode.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        migration_marker = config_path.parent / ".legacy-provider-imported"
        current: dict[str, Any] = {}
        if config_path.is_file():
            try:
                loaded = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    current = loaded
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError("CoreTest Agent configuration is invalid") from exc
        base = _opencode_provider_config(self.model_config)
        current["$schema"] = base["$schema"]
        current["share"] = "disabled"
        current["permission"] = base["permission"]
        if self.model_config.is_configured and not migration_marker.is_file():
            providers = current.get("provider")
            if not isinstance(providers, dict):
                providers = {}
            providers.update(base.get("provider") or {})
            current["provider"] = providers
            disabled = current.get("disabled_providers")
            current["disabled_providers"] = [
                item
                for item in disabled if isinstance(item, str) and item != "coretest"
            ] if isinstance(disabled, list) else []
            active = str(current.get("model") or "")
            if not active or active.startswith("coretest/"):
                current["model"] = base["model"]
                current["small_model"] = base["small_model"]
        staged = config_path.with_suffix(".tmp")
        staged.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staged.replace(config_path)
        if self.model_config.is_configured and not migration_marker.is_file():
            migration_marker.write_text(f"OpenCode {OPENCODE_VERSION}\n", encoding="ascii")
        return config_path

    def _active_model(self) -> tuple[str, str] | None:
        if self._config_path is None or not self._config_path.is_file():
            if self.model_config.is_configured:
                return "coretest", self.model_config.model or ""
            return None
        try:
            config = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        reference = str(config.get("model") or "")
        if "/" not in reference:
            return None
        provider_id, model_id = reference.split("/", 1)
        if provider_id in set(config.get("disabled_providers") or []):
            return None
        return provider_id, model_id

    def _message_model(self) -> dict[str, str]:
        active = self._active_model()
        if active is None:
            raise RuntimeError("CoreTest Agent model is not configured")
        return {"providerID": active[0], "modelID": active[1]}

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
            self._error = "CoreTest Agent model authentication failed"
            return False
        self._auth_configured = True
        return True

    def _require_healthy(self) -> None:
        deadline = monotonic() + max(5.0, self.config.health_timeout_seconds * 3)
        while True:
            if self.health()["healthy"]:
                return
            if not self.running or self._error == "CoreTest Agent model authentication failed":
                break
            if monotonic() >= deadline:
                break
            sleep(0.1)
        raise RuntimeError(self._error or "CoreTest Agent Runtime is unavailable")

    def native_request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        *,
        content_type: str = "application/json",
    ) -> OpenCodeNativeResponse:
        """Proxy the restricted OpenCode Web UI protocol without exposing Runtime auth."""
        self._require_healthy()
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            raise ValueError("invalid CoreTest Agent native UI path")
        route = parsed.path or "/"
        if not _native_ui_route_allowed(method, route):
            raise PermissionError(f"CoreTest Agent native UI route is disabled: {method} {route}")
        _validate_native_ui_mutation(method, route, body)

        query = parsed.query
        if not _native_ui_static_route(route) and not route.startswith("/global/"):
            parameters = [
                (name, value)
                for name, value in parse_qsl(query, keep_blank_values=True)
                if name
                not in {
                    "directory",
                    "workspace",
                    "location[directory]",
                    "host_session_id",
                }
            ]
            parameters.append(("directory", str(self._workspace or "")))
            query = urlencode(parameters)
        target = f"{self.config.base_url}{route}"
        if query:
            target += f"?{query}"
        request = Request(
            target,
            data=body,
            headers={
                **self._authorization_headers(),
                "Accept": "*/*",
                "Content-Type": content_type,
            },
            method=method,
        )
        try:
            response = self._urlopen(
                request,
                timeout=(
                    self.config.turn_timeout_seconds
                    if route in {"/event", "/global/event"}
                    else self.config.health_timeout_seconds
                ),
            )
        except HTTPError as exc:
            raw = self._sanitize_native_body(exc.read(), exc.headers.get_content_type())
            return OpenCodeNativeResponse(
                status=exc.code,
                body=raw,
                content_type=exc.headers.get("Content-Type", "application/json"),
            )
        except OSError as exc:
            raise RuntimeError(f"CoreTest Agent request failed: {method} {route}") from exc

        response_content_type = _response_header(
            response, "Content-Type", "application/octet-stream"
        )
        response_headers = {
            name: value
            for name in ("Cache-Control", "ETag", "Last-Modified")
            if (value := _response_header(response, name, ""))
        }
        status = int(getattr(response, "status", 200) or 200)
        if response_content_type.lower().startswith("text/event-stream"):
            return OpenCodeNativeResponse(
                status=status,
                content_type=response_content_type,
                headers=response_headers,
                stream=self._native_event_stream(response),
            )
        try:
            raw = response.read()
            if route == "/provider":
                raw = self._filter_native_provider_catalog(raw)
        finally:
            response.close()
        return OpenCodeNativeResponse(
            status=status,
            body=self._sanitize_native_body(raw, response_content_type),
            content_type=response_content_type,
            headers=response_headers,
        )

    def _filter_native_provider_catalog(self, raw: bytes) -> bytes:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("CoreTest Agent returned invalid provider data")
        if not isinstance(payload, dict):
            raise RuntimeError("CoreTest Agent returned invalid provider data")
        allowed = self._managed_provider_ids()
        all_providers = payload.get("all")
        if isinstance(all_providers, list):
            payload["all"] = [
                item
                for item in all_providers
                if isinstance(item, dict) and item.get("id") in allowed
            ]
        defaults = payload.get("default")
        if isinstance(defaults, dict):
            payload["default"] = {
                provider_id: model_id
                for provider_id, model_id in defaults.items()
                if provider_id in allowed
            }
        connected = payload.get("connected")
        if isinstance(connected, list):
            payload["connected"] = [
                provider_id for provider_id in connected if provider_id in allowed
            ]
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _managed_provider_ids(self) -> set[str]:
        if self._config_path is None or not self._config_path.is_file():
            return set()
        try:
            config = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        providers = config.get("provider")
        disabled = {
            item for item in config.get("disabled_providers") or [] if isinstance(item, str)
        }
        if not isinstance(providers, dict):
            return set()
        return {
            provider_id
            for provider_id in providers
            if isinstance(provider_id, str) and provider_id not in disabled
        }

    def _native_event_stream(self, response: Any) -> Iterator[bytes]:
        try:
            while True:
                line = response.readline()
                if not line:
                    return
                yield self._sanitize_native_body(line, "text/event-stream")
        finally:
            response.close()

    def _sanitize_native_body(self, raw: bytes, content_type: str) -> bytes:
        if self._workspace is None or not _native_text_content(content_type):
            return raw
        if content_type == "application/json":
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            else:
                return json.dumps(
                    self._sanitize_native_value(payload),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
        if content_type == "text/event-stream":
            try:
                text = raw.decode("utf-8")
                match = re.fullmatch(r"(?P<prefix>\s*data:\s?)(?P<body>.*?)(?P<ending>\r?\n)?", text)
                if match and match.group("body"):
                    payload = json.loads(match.group("body"))
                    sanitized = json.dumps(
                        self._sanitize_native_value(payload),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    return (
                        match.group("prefix")
                        + sanitized
                        + (match.group("ending") or "")
                    ).encode("utf-8")
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        return self._sanitize_native_raw(raw)

    def _sanitize_native_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._sanitize_native_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._sanitize_native_value(item) for item in value]
        if isinstance(value, str):
            return self._sanitize_native_text(value)
        return value

    def _sanitize_native_text(self, value: str) -> str:
        workspace = str(self._workspace or "")
        if not workspace:
            return value
        candidates = _workspace_text_candidates(workspace)
        sanitized = value
        for candidate in candidates:
            pattern = re.compile(
                r"\]\(\s*<?" + re.escape(candidate) + r"(?P<suffix>[^)\r\n>]*)>?\)",
                re.IGNORECASE,
            )
            sanitized = pattern.sub(
                lambda match: f"]({_workspace_file_link(match.group('suffix'))})",
                sanitized,
            )
        for candidate in candidates:
            sanitized = re.sub(
                re.escape(candidate),
                "CoreTest Workspace",
                sanitized,
                flags=re.IGNORECASE,
            )
        return self._rewrite_relative_workspace_links(sanitized)

    def _rewrite_relative_workspace_links(self, value: str) -> str:
        workspace = self._workspace
        if workspace is None:
            return value
        pattern = re.compile(r"\]\(\s*<?(?P<target>[^)\r\n>]+)>?\)")

        def replace(match: re.Match[str]) -> str:
            target = match.group("target").strip()
            if (
                not target
                or target.startswith(("/", "#"))
                or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", target)
                or target.lower().startswith("mailto:")
            ):
                return match.group(0)
            relative = unquote(target).replace("\\", "/")
            relative_path = re.sub(r":\d+(?::\d+)?$", "", relative)
            candidate = (workspace / relative_path).resolve()
            try:
                candidate.relative_to(workspace)
            except ValueError:
                return match.group(0)
            if not candidate.is_file():
                return match.group(0)
            return f"]({_workspace_file_link(relative)})"

        return pattern.sub(replace, value)

    def _sanitize_native_raw(self, raw: bytes) -> bytes:
        workspace = str(self._workspace)
        workspace_posix = workspace.replace("\\", "/")
        candidates = {workspace, workspace_posix}
        if re.match(r"^[A-Za-z]:/", workspace_posix):
            without_drive = workspace_posix[3:]
            candidates.update({without_drive, f"/{without_drive}"})
        sanitized = raw
        for candidate in candidates:
            escaped = json.dumps(candidate, ensure_ascii=False)[1:-1].encode("utf-8")
            sanitized = sanitized.replace(escaped, b"CoreTest Workspace")
            sanitized = sanitized.replace(candidate.encode("utf-8"), b"CoreTest Workspace")
            sanitized = sanitized.replace(
                quote(candidate, safe="").encode("ascii"), b"CoreTest%20Workspace"
            )
        return sanitized

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        result = self._request_value(method, path, payload, timeout=timeout)
        if not isinstance(result, dict):
            raise RuntimeError("CoreTest Agent returned an invalid response")
        return result

    def _request_value(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
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
            raise RuntimeError(f"CoreTest Agent request failed: {method} {path}") from exc
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("CoreTest Agent returned an invalid response") from exc

    def _authorization_headers(self) -> dict[str, str]:
        credentials = b64encode(f"opencode:{self._password}".encode()).decode()
        return {"Authorization": f"Basic {credentials}"}


def _opencode_state_root(env: Mapping[str, str]) -> Path:
    configured = str(env.get("CORETEST_OPENCODE_HOME") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = str(env.get("LOCALAPPDATA") or "").strip()
    root = Path(local_app_data) if local_app_data else Path.home() / ".hk-coretest"
    return (root / "HK-CoreTest" / "opencode").resolve()


def _prepare_host_cli(state_root: Path) -> Path:
    bin_directory = state_root / "bin"
    bin_directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        wrapper = bin_directory / "coretest-host.cmd"
        executable = str(Path(sys.executable).resolve()).replace('"', '""')
        if getattr(sys, "frozen", False):
            lines = [
                "@echo off",
                "@chcp 65001 >nul",
                f'"{executable}" --host-cli %*',
            ]
        else:
            source_root = str(Path(__file__).resolve().parents[1]).replace('"', '""')
            lines = [
                "@echo off",
                "@chcp 65001 >nul",
                f'set "PYTHONPATH={source_root}"',
                f'"{executable}" -m ai_gateway.host_cli %*',
            ]
        wrapper.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig")
        return bin_directory

    wrapper = bin_directory / "coretest-host"
    source_root = str(Path(__file__).resolve().parents[1])
    wrapper.write_text(
        "#!/bin/sh\n"
        f'PYTHONPATH="{source_root}" exec "{sys.executable}" -m ai_gateway.host_cli "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    return bin_directory


def _provider_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("provider id must be a string")
    result = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", result):
        raise ValueError("provider id must use letters, numbers, underscores or hyphens")
    return result


def _provider_probe_file(workspace: Path | None) -> Path | None:
    if workspace is None:
        return None
    readable_suffixes = {
        ".arxml", ".c", ".cfg", ".cpp", ".csv", ".dbc", ".h", ".hpp",
        ".ini", ".js", ".json", ".jsx", ".log", ".md", ".py", ".toml",
        ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
    }
    skipped_directories = {".git", ".hg", ".svn", "__pycache__", "node_modules"}
    inspected = 0
    for root, directories, files in os.walk(workspace):
        directories[:] = sorted(
            directory for directory in directories if directory not in skipped_directories
        )
        for name in sorted(files):
            inspected += 1
            if inspected > 2000:
                return None
            candidate = Path(root) / name
            if candidate.suffix.lower() not in readable_suffixes:
                continue
            try:
                size = candidate.stat().st_size
            except OSError:
                continue
            if 0 < size <= 256 * 1024:
                return candidate
    return None


def _model_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("model id must be a string")
    result = value.strip()
    if not result or len(result) > 200 or "\n" in result or "\r" in result:
        raise ValueError("model id is invalid")
    return result


def _provider_update(
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any], str | None, bool]:
    allowed = {"id", "name", "base_url", "api_key", "models", "activate"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unsupported provider fields: {', '.join(sorted(unknown))}")
    provider_id = _provider_id(payload.get("id"))
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError("provider name is required")
    base_url = payload.get("base_url")
    if not isinstance(base_url, str) or len(base_url.strip()) > 2048:
        raise ValueError("provider base URL is invalid")
    base_url = base_url.strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("provider base URL must be an http or https URL")
    api_key = payload.get("api_key")
    if api_key is not None:
        if not isinstance(api_key, str) or len(api_key.strip()) > 4096:
            raise ValueError("provider API key is invalid")
        api_key = api_key.strip() or None
    models = payload.get("models")
    if not isinstance(models, list) or not 1 <= len(models) <= 20:
        raise ValueError("provider must include between 1 and 20 models")
    model_config: dict[str, dict[str, str]] = {}
    for item in models:
        if not isinstance(item, dict) or set(item) - {"id", "name"}:
            raise ValueError("provider model is invalid")
        model_id = _model_id(item.get("id"))
        model_name = item.get("name")
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("model name is required")
        if model_id in model_config:
            raise ValueError("provider model ids must be unique")
        model_config[model_id] = {"name": model_name.strip()[:200]}
    activate = payload.get("activate", False)
    if not isinstance(activate, bool):
        raise ValueError("provider activate must be a boolean")
    provider = {
        "npm": "@ai-sdk/openai-compatible",
        "name": name.strip(),
        "options": {"baseURL": _openai_base_url(base_url)},
        "models": model_config,
    }
    return provider_id, provider, api_key, activate


def _validate_native_ui_mutation(method: str, route: str, body: bytes | None) -> None:
    method = method.upper()
    if method == "PUT" and route.startswith("/auth/"):
        _provider_id(route.rsplit("/", 1)[-1])
        payload = _native_json_body(body)
        if set(payload) != {"type", "key"} or payload.get("type") != "api":
            raise ValueError("only API key authentication is supported")
        key = payload.get("key")
        if not isinstance(key, str) or not key.strip() or len(key.strip()) > 4096:
            raise ValueError("provider API key is invalid")
        return
    if method == "DELETE" and route.startswith("/auth/"):
        _provider_id(route.rsplit("/", 1)[-1])
        return
    if method != "PATCH" or route != "/config":
        return

    payload = _native_json_body(body)
    unknown = set(payload) - {"provider", "disabled_providers"}
    if unknown:
        raise PermissionError(
            f"CoreTest Agent config fields are disabled: {', '.join(sorted(unknown))}"
        )
    disabled = payload.get("disabled_providers")
    if disabled is not None:
        if not isinstance(disabled, list):
            raise ValueError("disabled providers must be a list")
        for provider_id in disabled:
            _provider_id(provider_id)
    providers = payload.get("provider")
    if providers is None:
        return
    if not isinstance(providers, dict) or len(providers) != 1:
        raise ValueError("exactly one provider update is required")
    provider_id, config = next(iter(providers.items()))
    _provider_id(provider_id)
    if not isinstance(config, dict):
        raise ValueError("provider configuration is invalid")
    if set(config) - {"npm", "name", "options", "models"}:
        raise PermissionError("provider extensions and environment credentials are disabled")
    if config.get("npm") != "@ai-sdk/openai-compatible":
        raise PermissionError("only OpenAI-compatible providers are supported")
    options = config.get("options")
    if not isinstance(options, dict) or set(options) - {"baseURL", "headers"}:
        raise ValueError("provider options are invalid")
    if options.get("headers"):
        raise PermissionError("custom provider request headers are disabled")
    models = config.get("models")
    if not isinstance(models, dict):
        raise ValueError("provider models are invalid")
    _provider_update(
        {
            "id": provider_id,
            "name": config.get("name"),
            "base_url": options.get("baseURL"),
            "models": [
                {
                    "id": model_id,
                    "name": model.get("name") if isinstance(model, dict) else None,
                }
                for model_id, model in models.items()
            ],
        }
    )


def _native_json_body(body: bytes | None) -> dict[str, Any]:
    try:
        payload = json.loads((body or b"").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid CoreTest Agent configuration payload") from exc
    if not isinstance(payload, dict):
        raise ValueError("CoreTest Agent configuration payload must be an object")
    return payload


def _public_provider_catalog(
    config: dict[str, Any], provider_state: dict[str, Any]
) -> dict[str, Any]:
    connected = {
        item for item in provider_state.get("connected", []) if isinstance(item, str)
    }
    disabled = {item for item in config.get("disabled_providers", []) if isinstance(item, str)}
    reference = str(config.get("model") or "")
    active_provider_id, separator, active_model_id = reference.partition("/")
    if not separator or active_provider_id in disabled:
        active_provider_id = ""
        active_model_id = ""
    providers: list[dict[str, Any]] = []
    raw_providers = config.get("provider")
    if isinstance(raw_providers, dict):
        for provider_id, item in raw_providers.items():
            if not isinstance(provider_id, str) or provider_id in disabled or not isinstance(item, dict):
                continue
            raw_models = item.get("models")
            if not isinstance(raw_models, dict) or not raw_models:
                continue
            models = [
                {
                    "id": model_id,
                    "name": str(model.get("name") or model_id) if isinstance(model, dict) else model_id,
                }
                for model_id, model in raw_models.items()
                if isinstance(model_id, str)
            ]
            options = item.get("options") if isinstance(item.get("options"), dict) else {}
            providers.append(
                {
                    "id": provider_id,
                    "name": str(item.get("name") or provider_id),
                    "base_url": str(options.get("baseURL") or ""),
                    "models": models,
                    "api_key_configured": provider_id in connected,
                    "active": provider_id == active_provider_id,
                }
            )
    providers.sort(key=lambda item: (not item["active"], item["name"].lower()))
    return {
        "providers": providers,
        "active_provider_id": active_provider_id or None,
        "active_model_id": active_model_id or None,
    }


def _workspace_path(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute() or not candidate.is_dir():
        raise ValueError("workspace must be an existing absolute directory")
    workspace = candidate.resolve()
    if workspace.parent == workspace:
        raise ValueError("workspace cannot be a filesystem root")
    return workspace


def find_opencode_command(command: str) -> str | None:
    if command.lower() != "auto":
        candidate = Path(command).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        return shutil.which(command)

    executable = "opencode.exe" if os.name == "nt" else "opencode"
    for candidate in (
        Path(__file__).resolve().parent / "bin" / executable,
        Path(sys.executable).resolve().parent / executable,
        Path(sys.executable).resolve().parent / "opencode" / executable,
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
    return str(target.resolve()) if target.is_file() else None


def resolve_opencode_command(command: str) -> str | None:
    if installed := find_opencode_command(command):
        bundled = Path(__file__).resolve().parent / "bin" / "opencode.exe"
        if Path(installed).resolve() == bundled.resolve():
            _verify_bundled_opencode(Path(installed))
        return installed
    allow_download = os.getenv("OPENCODE_ALLOW_DOWNLOAD", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if command.lower() != "auto" or os.name != "nt" or not allow_download:
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


def _verify_bundled_opencode(path: Path) -> None:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest().lower() != OPENCODE_WINDOWS_EXE_SHA256:
        raise RuntimeError("Bundled CoreTest Agent Runtime failed SHA-256 verification")


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
                f"CoreTest Agent Runtime {OPENCODE_VERSION} download failed; check network access"
            ) from exc
        if digest.hexdigest().lower() != expected_sha256.lower():
            raise RuntimeError("CoreTest Agent Runtime download failed SHA-256 verification")
        try:
            with ZipFile(archive) as bundle:
                staged = target.with_suffix(".tmp")
                with bundle.open("opencode.exe") as source, staged.open("wb") as output:
                    shutil.copyfileobj(source, output)
                staged.replace(target)
        except (KeyError, OSError) as exc:
            target.with_suffix(".tmp").unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise RuntimeError("CoreTest Agent Runtime download archive is invalid") from exc


def _opencode_provider_config(model: ModelConfig) -> dict[str, Any]:
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "share": "disabled",
        "permission": {
            "read": "allow",
            "glob": "allow",
            "grep": "allow",
            "edit": "allow",
            "write": "allow",
            "apply_patch": "allow",
            "bash": "allow",
            "webfetch": "deny",
            "websearch": "deny",
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


def _session_permissions() -> list[dict[str, str]]:
    return [
        {"permission": name, "pattern": "*", "action": "allow"}
        for name in ("read", "glob", "grep", "list", "lsp", "edit", "apply_patch", "write", "bash")
    ] + [
        {"permission": "webfetch", "pattern": "*", "action": "deny"},
        {"permission": "websearch", "pattern": "*", "action": "deny"},
        {"permission": "task", "pattern": "*", "action": "deny"},
        {"permission": "external_directory", "pattern": "*", "action": "deny"}
    ]


def _public_event_id(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "", str(value or ""))[:100]


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


def _native_ui_route_allowed(method: str, route: str) -> bool:
    if method == "GET" and _native_ui_static_route(route):
        return True
    return any(
        re.fullmatch(pattern, route)
        for pattern in _NATIVE_UI_ROUTES.get(method.upper(), ())
    )


def _native_ui_static_route(route: str) -> bool:
    if route == "/" or route.startswith("/assets/"):
        return True
    return route in {
        "/apple-touch-icon-v3.png",
        "/favicon-96x96-v3.png",
        "/favicon-v3.ico",
        "/favicon-v3.svg",
        "/site.webmanifest",
        "/social-share.png",
    }


def _workspace_text_candidates(workspace: str) -> list[str]:
    posix = workspace.replace("\\", "/")
    candidates = {workspace, posix}
    if re.match(r"^[A-Za-z]:/", posix):
        without_drive = posix[3:]
        candidates.update({without_drive, f"/{without_drive}"})
    return sorted((item for item in candidates if item), key=len, reverse=True)


def _workspace_file_link(suffix: str) -> str:
    relative = suffix.strip().replace("\\", "/").lstrip("/")
    line = None
    line_match = re.search(r":(?P<line>\d+)(?::\d+)?$", relative)
    if line_match:
        line = line_match.group("line")
        relative = relative[: line_match.start()]
    encoded = quote(relative, safe="/._-~")
    target = f"/coretest-file/{encoded}"
    return f"{target}?line={line}" if line else target


def _native_text_content(content_type: str) -> bool:
    normalized = content_type.lower()
    return normalized.startswith("text/") or any(
        marker in normalized for marker in ("json", "javascript", "svg", "xml")
    )


def _response_header(response: Any, name: str, default: str) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return default
    value = headers.get(name)
    return str(value) if value else default


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
