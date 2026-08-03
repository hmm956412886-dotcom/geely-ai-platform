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
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic, sleep
from typing import Any, Callable, Iterator, Mapping
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
OPENCODE_WINDOWS_EXE_SHA256 = "8cc6228ced60be31b2b3408b5711f6922bc6654fba9ce63fed29264f2a4a01dd"


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
        self._workspace: Path | None = None
        self._config_directory: TemporaryDirectory[str] | None = None
        self._error: str | None = None
        self._auth_configured = False
        self._sessions: dict[str, str] = {}
        self._last_user_messages: dict[str, str] = {}
        self._pending_permissions: dict[str, dict[str, dict[str, Any]]] = {}
        self._rejected_sessions: set[str] = set()
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
            "installed": bool(self._command_probe(self.config.command)),
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
        with self._session_lock:
            self._sessions.clear()
            self._last_user_messages.clear()
            self._rejected_sessions.clear()
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
        try:
            result = self._request_json(
                "POST",
                f"/session/{quote(session_id, safe='')}/message",
                {
                    "system": system,
                    "parts": [{"type": "text", "text": prompt}],
                },
                timeout=max(self.model_config.timeout_seconds + 30, 600),
            )
        except RuntimeError:
            if self._take_rejection(host_session_id):
                return "已拒绝本次操作，OpenCode 未执行该工具。"
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
                return "已拒绝本次操作，OpenCode 未执行该工具。"
            raise RuntimeError("OpenCode returned an empty response")
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
                    "system": system,
                    "parts": [{"type": "text", "text": prompt}],
                },
            )
        except RuntimeError:
            response.close()
            if self._take_rejection(host_session_id):
                yield {"type": "error", "message": "本次操作已拒绝，OpenCode 未执行该工具。"}
                return
            raise
        yield {"type": "started"}
        text_parts: list[str] = []
        for event in self._read_events(response, session_id):
            if event.get("type") == "text_delta":
                text_parts.append(str(event.get("delta") or ""))
            if event.get("type") == "permission" and isinstance(event.get("permission"), dict):
                permission = event["permission"]
                permission_id = str(permission.get("id") or "")
                if permission_id:
                    with self._session_lock:
                        self._pending_permissions.setdefault(host_session_id, {})[
                            permission_id
                        ] = permission
            yield event
            if event.get("type") == "error":
                return
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
                raise RuntimeError("OpenCode did not create a session")
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
            raise RuntimeError("OpenCode returned invalid permission data")
        permissions = [
            self._public_permission(item)
            for item in result
            if isinstance(item, dict) and item.get("sessionID") == session_id
        ]
        with self._session_lock:
            self._pending_permissions[host_session_id] = {
                item["id"]: item for item in permissions if item["id"]
            }
        return permissions

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
            raise RuntimeError("OpenCode returned invalid activity data")
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
            return self._urlopen(request, timeout=None)
        except OSError as exc:
            raise RuntimeError("OpenCode event stream failed") from exc

    def _read_events(
        self, response: Any, session_id: str
    ) -> Iterator[dict[str, Any]]:
        try:
            while True:
                raw_line = response.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                public = self._public_event(event, session_id)
                if public is not None:
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
            return {"type": "text_delta", "delta": delta} if delta else None
        if event_type == "message.part.updated":
            part = properties.get("part")
            if not isinstance(part, dict) or part.get("type") != "tool":
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
            message = message or "OpenCode session failed"
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
            raise RuntimeError("OpenCode returned invalid diff data")
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
            raise RuntimeError("OpenCode returned invalid activity data")
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
        if reply == "reject":
            with self._session_lock:
                self._rejected_sessions.add(host_session_id)
        self._request_value(
            "POST",
            f"/permission/{quote(request_id, safe='')}/reply?directory={quote(str(self._workspace or ''), safe='')}",
            {"reply": reply},
        )
        with self._session_lock:
            self._pending_permissions.get(host_session_id, {}).pop(request_id, None)

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

    def _require_healthy(self) -> None:
        deadline = monotonic() + max(5.0, self.config.health_timeout_seconds * 3)
        while True:
            if self.health()["healthy"]:
                return
            if not self.running or self._error == "OpenCode model authentication failed":
                break
            if monotonic() >= deadline:
                break
            sleep(0.1)
        raise RuntimeError(self._error or "OpenCode Runtime is unavailable")

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
            raise RuntimeError("OpenCode returned an invalid response")
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
            raise RuntimeError(f"OpenCode request failed: {method} {path}") from exc
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("OpenCode returned an invalid response") from exc

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
        raise RuntimeError("Bundled OpenCode executable failed SHA-256 verification")


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
            "write": "deny",
            "apply_patch": "allow",
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


def _session_permissions() -> list[dict[str, str]]:
    return [
        {"permission": name, "pattern": "*", "action": "allow"}
        for name in ("read", "glob", "grep", "list", "lsp", "apply_patch")
    ] + [
        {"permission": name, "pattern": "*", "action": "ask"}
        for name in ("edit", "bash", "webfetch", "websearch")
    ] + [
        {"permission": "write", "pattern": "*", "action": "deny"},
        {"permission": "task", "pattern": "*", "action": "deny"},
        {"permission": "external_directory", "pattern": "*", "action": "deny"}
    ]


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
