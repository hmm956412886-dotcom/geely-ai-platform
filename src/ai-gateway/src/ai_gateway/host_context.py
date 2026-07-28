"""Session-isolated host software context for embedded Copilot clients."""

from __future__ import annotations

import re
import os
from threading import Lock
from typing import Any

from .access_control import access_control_enabled


DEFAULT_SESSION_ID = "default"
DEFAULT_MAX_HOST_SESSIONS = 256
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

ALLOWED_FIELDS = {
    "host_application",
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
    "selection_kind",
    "selection_label",
    "snapshot_revision",
}

DEFAULT_CONTEXT = {
    "host_application": "Demo Host",
    "project_id": "GEELY_TEST",
    "run_id": "RUN_CSV_001",
    "source_asset_id": "demo-current",
    "target_asset_id": "demo-target",
    "current_view": "test_result_detail",
    "user_id": None,
    "selection_kind": None,
    "selection_label": None,
    "snapshot_revision": None,
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
        context = _get_or_create_context(session_id)
        return {"host_session_id": session_id, **context}


def peek_host_context(host_session_id: str | None = None) -> dict[str, Any]:
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        context = _contexts.get(session_id, DEFAULT_CONTEXT)
        return {"host_session_id": session_id, **context}


def update_host_context(
    payload: dict[str, Any], host_session_id: str | None = None
) -> dict[str, Any]:
    session_id = normalize_host_session_id(host_session_id)
    unknown = set(payload) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"unsupported host context fields: {', '.join(sorted(unknown))}")
    direct_file_fields = {
        name for name in ("source_file", "baseline_file", "target_file") if payload.get(name)
    }
    if access_control_enabled() and direct_file_fields:
        raise ValueError(
            "direct file paths are disabled when Gateway access control is enabled; "
            "register host assets instead"
        )
    updates = {key: _clean_value(value) for key, value in payload.items()}
    with _lock:
        context = _get_or_create_context(session_id)
        context.update(updates)
        return {"host_session_id": session_id, **context}


def release_host_context(host_session_id: str | None) -> bool:
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        return _contexts.pop(session_id, None) is not None


def reset_host_context() -> dict[str, Any]:
    with _lock:
        _contexts.clear()
    return get_host_context()


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _get_or_create_context(session_id: str) -> dict[str, Any]:
    context = _contexts.get(session_id)
    if context is not None:
        return context
    if len(_contexts) >= _positive_env("AI_GATEWAY_MAX_HOST_SESSIONS", DEFAULT_MAX_HOST_SESSIONS):
        raise ValueError("host session limit reached; release an inactive host session")
    context = dict(DEFAULT_CONTEXT)
    _contexts[session_id] = context
    return context


def _positive_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value
