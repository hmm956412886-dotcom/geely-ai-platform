"""Minimal OpenAI-compatible chat client using only the Python standard library."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Callable
from urllib.request import Request

import httpx


Transport = Callable[[Request, float], bytes]


@dataclass(frozen=True)
class ModelConfig:
    base_url: str | None
    api_key: str | None
    model: str | None
    timeout_seconds: float = 30
    wire_api: str = "chat_completions"
    reasoning_effort: str | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": "openai-compatible",
            "configured": self.is_configured,
            "base_url": self.base_url,
            "model": self.model,
            "wire_api": self.wire_api,
            "reasoning_effort": self.reasoning_effort,
            "api_key_configured": bool(self.api_key),
            "timeout_seconds": self.timeout_seconds,
        }


def load_model_config(env: dict[str, str] | None = None) -> ModelConfig:
    env = env or os.environ
    timeout = float(env.get("AI_MODEL_TIMEOUT_SECONDS") or env.get("AI_TIMEOUT_SECONDS") or 30)
    wire_api = (env.get("AI_MODEL_WIRE_API") or "chat_completions").strip().lower()
    if wire_api not in {"chat_completions", "responses"}:
        raise ValueError("AI_MODEL_WIRE_API must be chat_completions or responses")
    return ModelConfig(
        base_url=env.get("AI_MODEL_BASE_URL") or env.get("AI_BASE_URL"),
        api_key=env.get("AI_MODEL_API_KEY") or env.get("AI_API_KEY"),
        model=env.get("AI_MODEL_NAME") or env.get("AI_CHAT_MODEL"),
        timeout_seconds=timeout,
        wire_api=wire_api,
        reasoning_effort=(env.get("AI_MODEL_REASONING_EFFORT") or "").strip() or None,
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
    if config.wire_api == "responses":
        payload = _responses_payload(config, messages)
        url = _responses_url(config.base_url or "")
    else:
        payload = {"model": config.model, "messages": messages, "temperature": 0.2}
        url = _chat_url(config.base_url or "")
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    raw = (transport or _httpx_transport)(request, config.timeout_seconds)
    response = json.loads(raw.decode("utf-8"))
    if config.wire_api == "responses":
        return _responses_text(response)
    try:
        return str(response["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("model api returned an unsupported response shape") from exc


def _chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _responses_payload(config: ModelConfig, messages: list[dict[str, str]]) -> dict[str, Any]:
    input_items = []
    for message in messages:
        role = "developer" if message.get("role") == "system" else message.get("role", "user")
        input_items.append(
            {
                "role": role,
                "content": [{"type": "input_text", "text": message.get("content", "")}],
            }
        )
    payload: dict[str, Any] = {"model": config.model, "input": input_items, "store": False}
    if config.reasoning_effort:
        payload["reasoning"] = {"effort": config.reasoning_effort}
    return payload


def _responses_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/responses"):
        return base
    return f"{base}/responses"


def _responses_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    output = response.get("output")
    if isinstance(output, list):
        parts = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if not isinstance(content, dict) or content.get("type") != "output_text":
                    continue
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        if parts:
            return "\n".join(parts)
    raise ValueError("model api returned an unsupported response shape")


def _httpx_transport(request: Request, timeout: float) -> bytes:
    try:
        response = httpx.request(
            request.get_method(),
            request.full_url,
            content=request.data,
            headers=dict(request.header_items()),
            timeout=timeout,
        )
    except httpx.RequestError as exc:
        raise ValueError(f"model api request failed: {exc}") from exc
    if response.is_error:
        raise ValueError(f"model api http error {response.status_code}: {response.text}")
    return response.content
