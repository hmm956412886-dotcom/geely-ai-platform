"""Command-line client for CoreTest's private read-only capability bridge."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="coretest-host",
        description="Query read-only capabilities provided by the running CoreTest host.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("capabilities", help="List available read-only capabilities")
    call = subparsers.add_parser("call", help="Invoke one read-only capability")
    call.add_argument("capability")
    call.add_argument(
        "--arguments",
        default="{}",
        help="JSON object passed to the capability",
    )
    call.add_argument(
        "--arg",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Simple string argument; may be repeated and avoids shell-specific JSON quoting",
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "capabilities":
            result = _request("GET", "/v1/capabilities")
        else:
            arguments = json.loads(args.arguments)
            if not isinstance(arguments, dict):
                raise ValueError("--arguments must be a JSON object")
            for item in args.arg:
                name, separator, value = item.partition("=")
                if not separator or not name.strip():
                    raise ValueError("--arg must use NAME=VALUE")
                arguments[name.strip()] = value
            result = _request(
                "POST",
                "/v1/invoke",
                {"capability": args.capability, "arguments": arguments},
            )
    except (HTTPError, URLError, json.JSONDecodeError, ValueError) as exc:
        message = _error_message(exc)
        print(f"coretest-host: {message}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    base_url = os.getenv("CORETEST_HOST_BRIDGE_URL", "").strip().rstrip("/")
    token = os.getenv("CORETEST_HOST_BRIDGE_TOKEN", "").strip()
    if not base_url or not token:
        raise ValueError("the running CoreTest host has not registered a capability bridge")
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def _error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            return str(payload.get("error") or exc.reason)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return str(exc.reason)
    return str(exc)


if __name__ == "__main__":
    raise SystemExit(main())
