"""OpenAI-compatible model configuration and client."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, MutableMapping
from urllib.parse import urlsplit


_MODEL_ENV_NAMES = {
    "AI_MODEL_BASE_URL",
    "AI_MODEL_API_KEY",
    "AI_MODEL_NAME",
    "AI_MODEL_OPTIONS",
}


@dataclass(frozen=True)
class ModelConfig:
    base_url: str | None
    api_key: str | None
    model: str | None
    timeout_seconds: float = 30
    available_models: tuple[str, ...] = ()

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": "openai-compatible",
            "configured": self.is_configured,
            "base_url": self.base_url,
            "model": self.model,
            "available_models": list(self.available_models),
            "api_key_configured": bool(self.api_key),
            "timeout_seconds": self.timeout_seconds,
        }


def load_model_config(env: dict[str, str] | None = None) -> ModelConfig:
    env = env if env is not None else os.environ
    timeout = float(env.get("AI_MODEL_TIMEOUT_SECONDS") or env.get("AI_TIMEOUT_SECONDS") or 30)
    model = env.get("AI_MODEL_NAME") or env.get("AI_CHAT_MODEL")
    return ModelConfig(
        base_url=env.get("AI_MODEL_BASE_URL") or env.get("AI_BASE_URL"),
        api_key=env.get("AI_MODEL_API_KEY") or env.get("AI_API_KEY"),
        model=model,
        timeout_seconds=timeout,
        available_models=tuple(_available_models(env.get("AI_MODEL_OPTIONS"), model)),
    )


def update_model_config(
    payload: dict[str, Any], env: MutableMapping[str, str] | None = None
) -> ModelConfig:
    unknown = set(payload) - {"base_url", "api_key", "model"}
    if unknown:
        raise ValueError(f"unsupported model config fields: {', '.join(sorted(unknown))}")
    if not payload:
        raise ValueError("model config must include at least one field")
    target_env = env if env is not None else os.environ
    current = load_model_config(dict(target_env))
    base_url = _config_value(payload, "base_url", current.base_url)
    api_key = _config_value(payload, "api_key", current.api_key, keep_blank=True)
    model = _config_value(payload, "model", current.model)
    if not base_url or not _is_http_url(base_url):
        raise ValueError("model base URL must be an http or https URL")
    if not api_key:
        raise ValueError("model API key is required")
    if not model:
        raise ValueError("model name is required")
    models = _available_models(target_env.get("AI_MODEL_OPTIONS"), current.model)
    if model not in models:
        models.append(model)
    values = {
        "AI_MODEL_BASE_URL": base_url,
        "AI_MODEL_API_KEY": api_key,
        "AI_MODEL_NAME": model,
        "AI_MODEL_OPTIONS": ",".join(models),
    }
    _write_model_config(_model_config_path(target_env), values)
    target_env.update(values)
    return load_model_config(dict(target_env))


def _config_value(
    payload: dict[str, Any], name: str, current: str | None, *, keep_blank: bool = False
) -> str | None:
    if name not in payload:
        return current
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"model {name.replace('_', ' ')} must be a string")
    if "\n" in value or "\r" in value:
        raise ValueError(f"model {name.replace('_', ' ')} must be one line")
    value = value.strip()
    if keep_blank and not value:
        return current
    limit = 4096 if name == "api_key" else 2048 if name == "base_url" else 200
    if len(value) > limit:
        raise ValueError(f"model {name.replace('_', ' ')} is too long")
    return value


def _is_http_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _available_models(raw: str | None, current: str | None) -> list[str]:
    values = [item.strip() for item in (raw or "").split(",")]
    models = list(dict.fromkeys(item for item in values if item and len(item) <= 200))
    if current and current not in models:
        models.append(current)
    return models[-20:]


def _model_config_path(env: MutableMapping[str, str]) -> Path:
    raw = str(env.get("AI_MODEL_CONFIG_FILE") or "").strip()
    if not raw:
        raise ValueError("model configuration file is unavailable")
    path = Path(raw).expanduser().resolve()
    if not path.parent.is_dir():
        raise ValueError("model configuration directory does not exist")
    return path


def _write_model_config(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    written: set[str] = set()
    result: list[str] = []
    for line in lines:
        name = line.split("=", 1)[0].strip() if "=" in line else ""
        if name not in _MODEL_ENV_NAMES:
            result.append(line)
            continue
        if name not in written:
            result.append(f"{name}={values[name]}")
            written.add(name)
    for name in _MODEL_ENV_NAMES:
        if name not in written:
            result.append(f"{name}={values[name]}")
    staged = path.with_name(f"{path.name}.tmp")
    staged.write_text("\n".join(result).rstrip() + "\n", encoding="utf-8")
    staged.replace(path)
