"""Optional bearer-token boundary for Gateway API requests."""

from __future__ import annotations

from hmac import compare_digest
import os
from typing import Mapping


ACCESS_TOKEN_ENV = "AI_GATEWAY_ACCESS_TOKEN"
HOST_TOKEN_ENV = "AI_GATEWAY_HOST_TOKEN"


def access_token() -> str:
    return os.getenv(ACCESS_TOKEN_ENV, "").strip()


def host_token() -> str:
    return os.getenv(HOST_TOKEN_ENV, "").strip()


def access_control_enabled() -> bool:
    return bool(access_token())


def is_authorized(headers: Mapping[str, str] | None) -> bool:
    expected = access_token()
    if not expected:
        return True
    credential = _bearer_credential(headers)
    return bool(credential) and any(
        compare_digest(credential, candidate)
        for candidate in (expected, host_token())
        if candidate
    )


def is_host_authorized(headers: Mapping[str, str] | None) -> bool:
    if not access_control_enabled():
        return True
    expected = host_token()
    credential = _bearer_credential(headers)
    return bool(expected and credential) and compare_digest(credential, expected)


def authorization_headers() -> dict[str, str]:
    token = access_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def validate_bind_access(host: str) -> None:
    if host.strip().lower() in {"127.0.0.1", "::1", "localhost"}:
        return
    missing = [
        name
        for name, value in (
            (ACCESS_TOKEN_ENV, access_token()),
            (HOST_TOKEN_ENV, host_token()),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            f"{', '.join(missing)} required when binding outside the local machine"
        )


def _bearer_credential(headers: Mapping[str, str] | None) -> str:
    authorization = _header(headers, "authorization")
    scheme, separator, credential = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return ""
    return credential.strip()


def _header(headers: Mapping[str, str] | None, name: str) -> str:
    if headers is None:
        return ""
    return next((str(value) for key, value in headers.items() if key.lower() == name), "")
