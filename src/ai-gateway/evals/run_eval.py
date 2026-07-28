from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from http.server import ThreadingHTTPServer
from threading import Thread
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_gateway.app import handle_request  # noqa: E402
from ai_gateway.access_control import (  # noqa: E402
    access_control_enabled,
    authorization_headers,
    host_token,
)
from ai_gateway.audit_log import clear_audit_events  # noqa: E402
from ai_gateway.server import GatewayHandler  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"
CASES = Path(__file__).with_name("eval_cases.json")


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    previous_base_url = os.environ.get("AI_GATEWAY_INTERNAL_BASE_URL")
    previous_agent_mode = os.environ.get("AI_AGENT_MODE")
    os.environ["AI_GATEWAY_INTERNAL_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
    os.environ["AI_AGENT_MODE"] = "deterministic"
    _register_eval_assets()
    clear_audit_events()
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    failures = 0
    try:
        for case in cases:
            error = run_case(case)
            if error:
                failures += 1
                print(f"FAIL {case['name']}: {error}")
            else:
                print(f"PASS {case['name']}")
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        _restore_env("AI_GATEWAY_INTERNAL_BASE_URL", previous_base_url)
        _restore_env("AI_AGENT_MODE", previous_agent_mode)
    print(f"{len(cases) - failures} passed, {failures} failed")
    return 1 if failures else 0


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def run_case(case: dict[str, Any]) -> str | None:
    body = case.get("body_raw", "")
    if "body" in case:
        body = json.dumps(_expand_paths(case["body"]), ensure_ascii=False)
    headers = authorization_headers()
    if case.get("host_privileged") and host_token():
        headers = {"Authorization": f"Bearer {host_token()}"}
    response = handle_request(case["method"], case["path"], body, headers=headers)
    if response.status != case["expect_status"]:
        return f"status {response.status} != {case['expect_status']}"
    payload = _json_or_text(response.body)
    for field, expected in case.get("expect", {}).items():
        actual = _field(payload, field)
        if actual != expected:
            return f"{field} {actual!r} != {expected!r}"
    for field, expected in case.get("contains", {}).items():
        actual = str(_field(payload, field))
        if expected not in actual:
            return f"{field} does not contain {expected!r}"
    for field, expected in case.get("prefix", {}).items():
        actual = str(_field(payload, field))
        if not actual.startswith(expected):
            return f"{field} does not start with {expected!r}"
    if case.get("body_contains") and case["body_contains"] not in response.body:
        return f"response body does not contain {case['body_contains']!r}"
    return None


def _register_eval_assets() -> None:
    headers = authorization_headers()
    if access_control_enabled():
        if not host_token():
            raise RuntimeError(
                "AI_GATEWAY_HOST_TOKEN is required to run evals with access control enabled"
            )
        headers = {"Authorization": f"Bearer {host_token()}"}
    for asset_id, fixture in (
        ("eval-current", "test-run-cases.csv"),
        ("eval-target", "test-run-cases-target.csv"),
    ):
        response = handle_request(
            "POST",
            "/api/v1/host/assets?host_session_id=eval-session",
            json.dumps(
                {"asset_id": asset_id, "file_path": str(FIXTURES / fixture)},
                ensure_ascii=False,
            ),
            headers=headers,
        )
        if response.status != 200:
            raise RuntimeError(f"failed to register eval asset {asset_id}: {response.body}")


def _expand_paths(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("${FIXTURES}", str(FIXTURES))
    if isinstance(value, dict):
        return {key: _expand_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_paths(item) for item in value]
    return value


def _json_or_text(body: str) -> Any:
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


def _field(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


if __name__ == "__main__":
    raise SystemExit(main())
