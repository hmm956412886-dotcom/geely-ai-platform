"""Private per-session workspace roots registered by the trusted desktop host."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

from .host_context import normalize_host_session_id


_workspaces: dict[str, Path] = {}
_lock = Lock()


def register_workspace(
    payload: dict[str, Any], host_session_id: str | None = None
) -> dict[str, Any]:
    unknown = set(payload) - {"project_root"}
    if unknown:
        raise ValueError(f"unsupported workspace fields: {', '.join(sorted(unknown))}")
    raw_root = payload.get("project_root")
    if not isinstance(raw_root, str) or not raw_root.strip():
        raise ValueError("project_root is required")
    candidate = Path(raw_root).expanduser()
    if not candidate.is_absolute() or not candidate.is_dir():
        raise ValueError("project_root must be an existing directory with an absolute path")
    root = candidate.resolve()
    if root.parent == root:
        raise ValueError("project_root cannot be a filesystem root")
    if _is_product_source_root(root):
        raise ValueError("project_root cannot be a CoreTest or CoreTest Agent product source root")

    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        other_roots = {
            workspace for key, workspace in _workspaces.items() if key != session_id
        }
        if other_roots and root not in other_roots:
            raise ValueError("Gateway is already bound to another workspace")
        _workspaces[session_id] = root
    return {
        "host_session_id": session_id,
        "registered": True,
        "workspace_name": root.name,
    }


def get_workspace_path(host_session_id: str | None = None) -> Path | None:
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        return _workspaces.get(session_id)


def get_workspace_status(host_session_id: str | None = None) -> dict[str, Any]:
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        root = _workspaces.get(session_id)
    return {
        "host_session_id": session_id,
        "registered": root is not None,
        "workspace_name": root.name if root else None,
    }


def release_workspace(host_session_id: str | None) -> bool:
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        return _workspaces.pop(session_id, None) is not None


def workspace_count() -> int:
    with _lock:
        return len(_workspaces)


def reset_workspaces() -> None:
    with _lock:
        _workspaces.clear()


def _is_product_source_root(root: Path) -> bool:
    return (
        (root / "frontend" / "copilot-shell").is_dir()
        and (root / "src" / "ai-gateway" / "src" / "ai_gateway").is_dir()
    ) or (root / "app" / "coretest_copilot").is_dir()
