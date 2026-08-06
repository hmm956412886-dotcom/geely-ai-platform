"""Bounded, session-isolated facts captured from a trusted desktop host."""

from __future__ import annotations

import json
import os
from threading import Lock
from typing import Any

from .host_context import get_host_context, normalize_host_session_id


DEFAULT_MAX_SNAPSHOT_BYTES = 1024 * 1024
ALLOWED_KINDS = {"project", "file", "trace", "dbc", "diagnostic", "pdx"}
ALLOWED_FIELDS = {"kind", "revision", "captured_at", "selection", "data"}

_snapshots: dict[str, dict[str, Any]] = {}
_lock = Lock()


def update_host_snapshot(
    payload: dict[str, Any], host_session_id: str | None = None
) -> dict[str, Any]:
    unknown = set(payload) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"unsupported host snapshot fields: {', '.join(sorted(unknown))}")
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"unsupported host snapshot kind: {kind or 'empty'}")
    revision = str(payload.get("revision") or "").strip()
    if not revision or len(revision) > 80:
        raise ValueError("snapshot revision is required and must be at most 80 characters")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("snapshot data must be a JSON object")
    selection = payload.get("selection")
    if selection is not None and not isinstance(selection, dict):
        raise ValueError("snapshot selection must be a JSON object")

    snapshot = {
        "kind": kind,
        "revision": revision,
        "captured_at": _optional_text(payload.get("captured_at")),
        "selection": selection or {},
        "data": data,
    }
    try:
        encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("snapshot must contain JSON-compatible values") from exc
    if len(encoded) > _positive_env("AI_GATEWAY_MAX_HOST_SNAPSHOT_BYTES", DEFAULT_MAX_SNAPSHOT_BYTES):
        raise ValueError("host snapshot exceeds the configured size limit")

    session_id = normalize_host_session_id(host_session_id)
    get_host_context(session_id)
    with _lock:
        _snapshots[session_id] = snapshot
    return {"host_session_id": session_id, **snapshot, "size_bytes": len(encoded)}


def get_host_snapshot(host_session_id: str | None = None) -> dict[str, Any]:
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        snapshot = _snapshots.get(session_id)
        return {"host_session_id": session_id, **snapshot} if snapshot else {
            "host_session_id": session_id,
            "kind": None,
            "revision": None,
            "captured_at": None,
            "selection": {},
            "data": {},
        }


def release_host_snapshot(host_session_id: str | None) -> bool:
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        return _snapshots.pop(session_id, None) is not None


def reset_host_snapshots() -> None:
    with _lock:
        _snapshots.clear()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value
