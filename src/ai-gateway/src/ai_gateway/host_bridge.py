"""Private loopback bridge registered by the trusted CoreTest connector."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

from .host_context import normalize_host_session_id


@dataclass(frozen=True)
class HostBridgeConfig:
    url: str
    token: str


_bridges: dict[str, HostBridgeConfig] = {}
_lock = Lock()


def register_host_bridge(
    payload: dict[str, Any], host_session_id: str | None = None
) -> dict[str, Any]:
    bridge = validate_host_bridge(payload)
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        _bridges[session_id] = bridge
    return {"host_session_id": session_id, "available": True}


def validate_host_bridge(payload: dict[str, Any]) -> HostBridgeConfig:
    unknown = set(payload) - {"url", "token"}
    if unknown:
        raise ValueError(f"unsupported host bridge fields: {', '.join(sorted(unknown))}")
    url = payload.get("url")
    token = payload.get("token")
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("host bridge URL is invalid")
    parsed = urlsplit(url.rstrip("/"))
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
        raise ValueError("host bridge must use an HTTP loopback URL with an explicit port")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("host bridge URL is invalid")
    if not isinstance(token, str) or not 16 <= len(token) <= 512:
        raise ValueError("host bridge token is invalid")

    return HostBridgeConfig(url=url.rstrip("/"), token=token)


def get_host_bridge(host_session_id: str | None = None) -> HostBridgeConfig | None:
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        return _bridges.get(session_id)


def release_host_bridge(host_session_id: str | None) -> bool:
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        return _bridges.pop(session_id, None) is not None


def reset_host_bridges() -> None:
    with _lock:
        _bridges.clear()
