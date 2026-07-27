"""In-process host software context for the Copilot MVP."""

from __future__ import annotations

from threading import Lock
from typing import Any


ALLOWED_FIELDS = {
    "project_id",
    "run_id",
    "source_file",
    "baseline_file",
    "target_file",
    "current_view",
    "user_id",
}

DEFAULT_CONTEXT = {
    "project_id": "GEELY_TEST",
    "run_id": "RUN_CSV_001",
    "source_file": r"D:\geely-ai-platform\src\ai-gateway\tests\fixtures\test-run-cases.csv",
    "target_file": r"D:\geely-ai-platform\src\ai-gateway\tests\fixtures\test-run-cases-target.csv",
    "current_view": "test_result_detail",
    "user_id": None,
}

_context = dict(DEFAULT_CONTEXT)
_lock = Lock()


def get_host_context() -> dict[str, Any]:
    with _lock:
        return dict(_context)


def update_host_context(payload: dict[str, Any]) -> dict[str, Any]:
    unknown = set(payload) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"unsupported host context fields: {', '.join(sorted(unknown))}")
    updates = {key: _clean_value(value) for key, value in payload.items()}
    with _lock:
        _context.update(updates)
        return dict(_context)


def reset_host_context() -> dict[str, Any]:
    with _lock:
        _context.clear()
        _context.update(DEFAULT_CONTEXT)
        return dict(_context)


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
