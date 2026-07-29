"""OpenAI-compatible model configuration and client."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from openai import OpenAI, OpenAIError


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
    client: Any | None = None,
) -> str:
    config = config or load_model_config()
    if not config.is_configured:
        raise ValueError("model api is not configured")

    model_client = client or OpenAI(
        api_key=config.api_key,
        base_url=_openai_base_url(config.base_url or ""),
        timeout=config.timeout_seconds,
        max_retries=0,
    )
    try:
        if config.wire_api == "responses":
            kwargs: dict[str, Any] = {
                "model": config.model,
                "input": [
                    {
                        "role": "developer" if item.get("role") == "system" else item.get("role", "user"),
                        "content": item.get("content", ""),
                    }
                    for item in messages
                ],
                "store": False,
            }
            if config.reasoning_effort:
                kwargs["reasoning"] = {"effort": config.reasoning_effort}
            response = model_client.responses.create(**kwargs)
            answer = getattr(response, "output_text", None)
        else:
            response = model_client.chat.completions.create(
                model=config.model,
                messages=messages,
                temperature=0.2,
            )
            answer = response.choices[0].message.content
    except OpenAIError as exc:
        raise ValueError(f"model api request failed: {exc}") from exc

    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("model api returned an empty response")
    return answer.strip()


def _openai_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized
