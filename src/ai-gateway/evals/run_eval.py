from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_gateway.app import handle_request  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"
CASES = Path(__file__).with_name("eval_cases.json")


def main() -> int:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    failures = 0
    for case in cases:
        error = run_case(case)
        if error:
            failures += 1
            print(f"FAIL {case['name']}: {error}")
        else:
            print(f"PASS {case['name']}")
    print(f"{len(cases) - failures} passed, {failures} failed")
    return 1 if failures else 0


def run_case(case: dict[str, Any]) -> str | None:
    body = case.get("body_raw", "")
    if "body" in case:
        body = json.dumps(_expand_paths(case["body"]), ensure_ascii=False)
    response = handle_request(case["method"], case["path"], body)
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
