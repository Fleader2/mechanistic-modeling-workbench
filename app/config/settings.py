"""Environment-driven application configuration.

Mirrors the settings pattern used across the sibling agent repositories
(e.g. ``agent1-biochemical-curator/app/config/settings.py``): no credential
is ever given a default value, and configuration is read once per process
via ``get_settings``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

APPLICATION_NAME = "Mechanistic Modeling Workbench"
API_V1_PREFIX = "/api/v1"

LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]


class Settings(BaseSettings):
    """Runtime configuration read from the environment or a local ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["local", "test", "ci", "production"] = "local"
    log_level: LogLevel = "INFO"

    database_url: PostgresDsn
    """Canonical PostgreSQL database. Required; no default is supplied."""

    test_database_url: PostgresDsn | None = None
    """Separate database used by the test suite. Tests refuse to run without it."""

    database_echo: bool = False

    cors_allow_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    """Origins the HTTP API accepts cross-origin requests from.

    Defaults to the Vite dev server's own default port, since the frontend
    (``frontend/``) and this API are two separately-run processes during
    local development, not one origin. Override via a JSON array in the
    ``CORS_ALLOW_ORIGINS`` environment variable for any other deployment.
    """

    artifacts_dir: str = "artifacts"
    """Local filesystem directory (relative to the process's own working directory, unless an
    absolute path is given) this Workbench writes its own durable file artifacts into --
    currently just ``<artifacts_dir>/datasets/<sha256>.xlsx`` for a saved time-series dataset
    import (``app.storage``). Mirrors the naming convention the sibling Harness repository
    already uses for its own transient ``artifacts/runs/``, per ``docs/15_gui_backend
    _integration_audit.md``'s own suggestion. Local disk is one valid implementation of the
    Workbench's own existing ``artifact_reference``-as-opaque-string contract -- swapping it
    for S3-compatible object storage later requires no schema change.
    """

    @property
    def sqlalchemy_url(self) -> str:
        """Database URL with an explicit driver.

        SQLAlchemy defaults the bare ``postgresql://`` scheme to psycopg2, which
        this project does not install. The driver is made explicit rather than
        letting connection fail with a confusing import error.
        """
        url = str(self.database_url)
        for bare_scheme in ("postgresql://", "postgres://"):
            if url.startswith(bare_scheme):
                return "postgresql+psycopg://" + url[len(bare_scheme) :]
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings instance.

    Cached so that configuration is read once per process. Tests call
    ``get_settings.cache_clear()`` after changing the environment.
    """
    return Settings()  # type: ignore[call-arg]
