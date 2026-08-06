"""Optional bearer-token boundary for Gateway API requests."""

from __future__ import annotations

from base64 import b64decode
from hashlib import sha256
from hmac import compare_digest, new as new_hmac
from http.cookies import CookieError, SimpleCookie
import os
from typing import Mapping


ACCESS_TOKEN_ENV = "AI_GATEWAY_ACCESS_TOKEN"
HOST_TOKEN_ENV = "AI_GATEWAY_HOST_TOKEN"
NATIVE_UI_COOKIE = "coretest_native_auth"


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


def is_native_ui_authorized(
    headers: Mapping[str, str] | None, host_session_id: str | None = None
) -> bool:
    """Accept the Gateway token in OpenCode Web UI's Basic-auth shape."""
    expected = access_token()
    if not expected:
        return True
    credential = _basic_password(headers)
    if credential and compare_digest(credential, expected):
        return True
    cookie = _cookie_value(headers, NATIVE_UI_COOKIE)
    signed = native_ui_cookie_value(host_session_id)
    return bool(cookie and signed) and compare_digest(cookie, signed)


def native_ui_cookie_value(host_session_id: str | None) -> str:
    token = access_token()
    session = str(host_session_id or "").strip()
    if not token or not session:
        return ""
    return new_hmac(
        token.encode("utf-8"),
        f"coretest-native-ui:{session}".encode("utf-8"),
        sha256,
    ).hexdigest()


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


def _basic_password(headers: Mapping[str, str] | None) -> str:
    authorization = _header(headers, "authorization")
    scheme, separator, credential = authorization.partition(" ")
    if not separator or scheme.lower() != "basic":
        return ""
    try:
        decoded = b64decode(credential.strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""
    username, separator, password = decoded.partition(":")
    if not separator or username != "opencode":
        return ""
    return password


def _cookie_value(headers: Mapping[str, str] | None, name: str) -> str:
    raw = _header(headers, "cookie")
    if not raw:
        return ""
    cookie = SimpleCookie()
    try:
        cookie.load(raw)
    except CookieError:
        return ""
    item = cookie.get(name)
    return item.value if item is not None else ""


def _header(headers: Mapping[str, str] | None, name: str) -> str:
    if headers is None:
        return ""
    return next((str(value) for key, value in headers.items() if key.lower() == name), "")
