"""Authenticated loopback HTTP transport for read-only CoreTest capabilities."""

from __future__ import annotations

from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
from threading import Thread
from typing import Any, Callable


MAX_REQUEST_BYTES = 64 * 1024


class ReadOnlyHostBridge:
    def __init__(
        self,
        *,
        capabilities: list[dict[str, Any]],
        invoke: Callable[[str, dict[str, Any]], dict[str, Any]],
        token: str | None = None,
    ) -> None:
        self._capabilities = capabilities
        self._capability_names = {str(item.get("name") or "") for item in capabilities}
        self._invoke = invoke
        self._token = token or secrets.token_urlsafe(32)
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def registration(self) -> dict[str, str]:
        if self._server is None:
            raise RuntimeError("CoreTest host bridge is not running")
        return {
            "url": f"http://127.0.0.1:{self._server.server_port}",
            "token": self._token,
        }

    def start(self) -> None:
        if self._server is not None:
            return
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if not self._authorized():
                    return
                if self.path != "/v1/capabilities":
                    self._json(404, {"error": "not found"})
                    return
                self._json(200, {"capabilities": bridge._capabilities})

            def do_POST(self) -> None:
                if not self._authorized():
                    return
                if self.path != "/v1/invoke":
                    self._json(404, {"error": "not found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    if length <= 0 or length > MAX_REQUEST_BYTES:
                        raise ValueError("request body is invalid")
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not isinstance(payload, dict) or set(payload) - {
                        "capability",
                        "arguments",
                    }:
                        raise ValueError("request fields are invalid")
                    capability = payload.get("capability")
                    arguments = payload.get("arguments", {})
                    if capability not in bridge._capability_names:
                        raise ValueError("unknown or unavailable capability")
                    if not isinstance(arguments, dict):
                        raise ValueError("capability arguments must be an object")
                    result = bridge._invoke(str(capability), arguments)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                except Exception as exc:
                    self._json(500, {"error": str(exc)[:500]})
                    return
                self._json(200, {"result": result})

            def _authorized(self) -> bool:
                supplied = self.headers.get("Authorization", "")
                expected = f"Bearer {bridge._token}"
                if compare_digest(supplied, expected):
                    return True
                self._json(401, {"error": "unauthorized"})
                return False

            def _json(self, status: int, payload: dict[str, Any]) -> None:
                encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = Thread(
            target=self._server.serve_forever,
            name="coretest-host-bridge",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)
