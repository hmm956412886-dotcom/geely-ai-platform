"""In-process mapping from browser-safe asset IDs to host-local files."""

from __future__ import annotations

from pathlib import Path
import os
import re
from threading import Lock
from typing import Any
from uuid import uuid4

from .host_context import get_host_context, normalize_host_session_id


ASSET_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
DEFAULT_MAX_ASSETS_PER_SESSION = 32
SUPPORTED_SUFFIXES = {".csv": "text/csv", ".json": "application/json"}

_assets: dict[str, dict[str, Path]] = {}
_lock = Lock()


def register_host_asset(payload: dict[str, Any], host_session_id: str | None = None) -> dict[str, Any]:
    unknown = set(payload) - {"asset_id", "file_path"}
    if unknown:
        raise ValueError(f"unsupported host asset fields: {', '.join(sorted(unknown))}")
    file_path = str(payload.get("file_path") or "").strip()
    if not file_path:
        raise ValueError("file_path is required")
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise ValueError("host asset file does not exist")
    media_type = SUPPORTED_SUFFIXES.get(path.suffix.lower())
    if media_type is None:
        raise ValueError(f"unsupported host asset type: {path.suffix}")

    session_id = normalize_host_session_id(host_session_id)
    get_host_context(session_id)
    asset_id = str(payload.get("asset_id") or f"asset-{uuid4().hex}").strip()
    if not ASSET_ID_PATTERN.fullmatch(asset_id):
        raise ValueError("invalid asset_id")
    with _lock:
        session_assets = _assets.setdefault(session_id, {})
        if (
            asset_id not in session_assets
            and len(session_assets)
            >= _positive_env(
                "AI_GATEWAY_MAX_ASSETS_PER_SESSION", DEFAULT_MAX_ASSETS_PER_SESSION
            )
        ):
            raise ValueError("host asset limit reached for this session")
        session_assets[asset_id] = path.resolve()
    return {
        "asset_id": asset_id,
        "name": path.name,
        "media_type": media_type,
        "size_bytes": path.stat().st_size,
    }


def resolve_host_asset(asset_id: str, host_session_id: str | None = None) -> str:
    session_id = normalize_host_session_id(host_session_id)
    if asset_id in {"demo-current", "demo-target"}:
        fixture_name = (
            "test-run-cases.csv" if asset_id == "demo-current" else "test-run-cases-target.csv"
        )
        return str(Path(__file__).resolve().parents[2] / "tests" / "fixtures" / fixture_name)
    with _lock:
        path = _assets.get(session_id, {}).get(asset_id)
    if path is None:
        raise ValueError(f"unknown host asset: {asset_id}")
    return str(path)


def reset_host_assets() -> None:
    with _lock:
        _assets.clear()


def release_host_assets(host_session_id: str | None) -> int:
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        return len(_assets.pop(session_id, {}))


def _positive_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value
