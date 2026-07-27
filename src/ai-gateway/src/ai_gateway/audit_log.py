"""Small in-process audit event log for the AI Gateway MVP."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any


MAX_EVENTS = 100

_events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
_lock = Lock()


def append_audit_event(
    *,
    method: str,
    path: str,
    status: int,
    request_id: str | None,
    context: dict[str, Any],
    error_code: str | None = None,
) -> None:
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": method,
        "path": path,
        "status": status,
        "request_id": request_id,
        "error_code": error_code,
        "project_id": context.get("project_id"),
        "run_id": context.get("run_id"),
        "user_id": context.get("user_id"),
        "current_view": context.get("current_view"),
    }
    with _lock:
        _events.append(event)


def list_audit_events(limit: int = 50) -> list[dict[str, Any]]:
    limit = max(0, min(limit, MAX_EVENTS))
    with _lock:
        return list(_events)[-limit:]


def clear_audit_events() -> None:
    with _lock:
        _events.clear()
