"""Database connection helpers for the Feishu sync worker."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


class DatabaseConfigurationError(ValueError):
    """Raised when database configuration is missing or invalid."""


@dataclass(frozen=True)
class DatabaseSettings:
    url: str


def load_database_settings(database_url: str | None = None) -> DatabaseSettings:
    url = (database_url or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise DatabaseConfigurationError(
            "DATABASE_URL is required unless --database-url is provided"
        )
    return DatabaseSettings(url=url)


def connect(settings: DatabaseSettings) -> Any:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is required for database persistence; install the "
            "worker dependencies first"
        ) from exc
    return psycopg.connect(settings.url)

