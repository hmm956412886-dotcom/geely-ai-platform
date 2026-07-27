"""Minimal OpenAI-compatible chat client using only the Python standard library."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


Transport = Callable[[Request, float], bytes]


@dataclass(frozen=True)
class ModelConfig:
    base_url: str | None
    api_key: str | None
    model: str | None
    timeout_seconds: float = 30

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": "openai-compatible",
            "configured": self.is_configured,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_configured": bool(self.api_key),
            "timeout_seconds": self.timeout_seconds,
        }


def load_model_config(env: dict[str, str] | None = None) -> ModelConfig:
    env = env or os.environ
    timeout = float(env.get("AI_MODEL_TIMEOUT_SECONDS") or env.get("AI_TIMEOUT_SECONDS") or 30)
    return ModelConfig(
        base_url=env.get("AI_MODEL_BASE_URL") or env.get("AI_BASE_URL"),
        api_key=env.get("AI_MODEL_API_KEY") or env.get("AI_API_KEY"),
        model=env.get("AI_MODEL_NAME") or env.get("AI_CHAT_MODEL"),
        timeout_seconds=timeout,
    )


def chat_completion(
    messages: list[dict[str, str]],
    *,
    config: ModelConfig | None = None,
    transport: Transport | None = None,
) -> str:
    config = config or load_model_config()
    if not config.is_configured:
        raise ValueError("model api is not configured")
    payload = {"model": config.model, "messages": messages, "temperature": 0.2}
    request = Request(
        _chat_url(config.base_url or ""),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    raw = (transport or _urlopen_transport)(request, config.timeout_seconds)
    response = json.loads(raw.decode("utf-8"))
    try:
        return str(response["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("model api returned an unsupported response shape") from exc


def _chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _urlopen_transport(request: Request, timeout: float) -> bytes:
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"model api http error {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ValueError(f"model api request failed: {exc.reason}") from exc
