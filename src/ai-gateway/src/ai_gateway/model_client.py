"""OpenAI-compatible model configuration and client."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


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
