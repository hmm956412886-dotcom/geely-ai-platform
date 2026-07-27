"""Session-isolated host software context for embedded Copilot clients."""

from __future__ import annotations

import re
from threading import Lock
from typing import Any


DEFAULT_SESSION_ID = "default"
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

ALLOWED_FIELDS = {
    "project_id",
    "run_id",
    "source_asset_id",
    "target_asset_id",
    "baseline_asset_id",
    "source_file",
    "baseline_file",
    "target_file",
    "current_view",
    "user_id",
}

DEFAULT_CONTEXT = {
    "project_id": "GEELY_TEST",
    "run_id": "RUN_CSV_001",
    "source_asset_id": "demo-current",
    "target_asset_id": "demo-target",
    "current_view": "test_result_detail",
    "user_id": None,
}

_contexts: dict[str, dict[str, Any]] = {}
_lock = Lock()


def normalize_host_session_id(host_session_id: str | None) -> str:
    session_id = (host_session_id or DEFAULT_SESSION_ID).strip()
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError("invalid host_session_id")
    return session_id


def get_host_context(host_session_id: str | None = None) -> dict[str, Any]:
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        context = _contexts.setdefault(session_id, dict(DEFAULT_CONTEXT))
        return {"host_session_id": session_id, **context}


def update_host_context(
    payload: dict[str, Any], host_session_id: str | None = None
) -> dict[str, Any]:
    session_id = normalize_host_session_id(host_session_id)
    unknown = set(payload) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"unsupported host context fields: {', '.join(sorted(unknown))}")
    updates = {key: _clean_value(value) for key, value in payload.items()}
    with _lock:
        context = _contexts.setdefault(session_id, dict(DEFAULT_CONTEXT))
        context.update(updates)
        return {"host_session_id": session_id, **context}


def reset_host_context() -> dict[str, Any]:
    with _lock:
        _contexts.clear()
    return get_host_context()


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
