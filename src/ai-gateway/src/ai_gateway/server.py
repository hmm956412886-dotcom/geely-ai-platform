"""HTTP server for the dependency-free AI Gateway MVP."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import os
from typing import Sequence

from .access_control import validate_bind_access
from .app import Response, handle_request
from .opencode_runtime import reset_opencode_runtime


class GatewayHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send(handle_request("GET", self.path, headers=self.headers))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        self._send(handle_request("POST", self.path, body, headers=self.headers))

    def do_DELETE(self) -> None:
        self._send(handle_request("DELETE", self.path, headers=self.headers))

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, response: Response) -> None:
        encoded = response.body.encode("utf-8") if isinstance(response.body, str) else response.body
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(encoded)))
        for name, value in (response.headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(encoded)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="geely-ai-gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args(argv)
    try:
        validate_bind_access(args.host)
    except ValueError as exc:
        parser.error(str(exc))
    os.environ.setdefault(
        "AI_GATEWAY_INTERNAL_BASE_URL",
        f"http://127.0.0.1:{args.port}",
    )
    server = ThreadingHTTPServer((args.host, args.port), GatewayHandler)
    print(f"Geely AI Gateway listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        reset_opencode_runtime()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
