"""Application configuration.

A single validated model is the only place the process reads the environment.
Anything that fails validation aborts the boot instead of surfacing as a runtime
error deep inside a request.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]
LogLevel = Literal["critical", "error", "warning", "info", "debug"]

# The sibling backend uses the level vocabulary of its logging library. Both
# spellings are accepted so one `.env` file can drive either implementation.
_LOG_LEVEL_ALIASES = {
    "fatal": "critical",
    "warn": "warning",
    "trace": "debug",
    "silent": "critical",
}

_MIN_SECRET_LENGTH = 32
_ASYNC_DRIVER = "postgresql+asyncpg"
_ACCEPTED_DB_SCHEMES = {"postgresql", "postgres", _ASYNC_DRIVER}


class Settings(BaseSettings):
    """Validated view of the process environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: AppEnv = "development"
    host: str = Field(default="0.0.0.0", min_length=1)
    port: int = Field(default=8000, ge=1, le=65_535)
    log_level: LogLevel = "info"
    # ``NoDecode`` keeps the raw environment string intact. Without it the
    # settings source JSON-decodes a ``list[str]`` field before any validator
    # runs, so the comma-separated form operators actually write would fail the
    # boot with a JSON parse error. The validator below accepts both spellings.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3100"]
    )
    json_body_limit_bytes: int = Field(default=1_048_576, ge=1_024, le=67_108_864)

    database_url: str
    jwt_access_secret: str = Field(min_length=_MIN_SECRET_LENGTH)
    jwt_refresh_secret: str = Field(min_length=_MIN_SECRET_LENGTH)

    redis_url: str
    redis_key_prefix: str = Field(default="crm:", min_length=1)
    cache_ttl_seconds: int = Field(default=300, ge=1, le=86_400)

    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3_600)
    rate_limit_max_requests: int = Field(default=300, ge=1, le=100_000)
    auth_rate_limit_max_requests: int = Field(default=10, ge=1, le=10_000)

    mongodb_url: str
    event_log_retention_days: int = Field(default=90, ge=1, le=3_650)

    ws_path: str = Field(default="/api/v1/realtime", pattern=r"^/")

    # Delivery integration. Every default keeps the module on the in-repo stub
    # transport, so a fresh checkout answers the integration endpoints without a
    # carrier account; only a base URL switches it to a real provider.
    delivery_base_url: str | None = None
    delivery_api_key: str | None = None
    delivery_timeout_ms: int = Field(default=5_000, ge=100, le=120_000)
    delivery_max_attempts: int = Field(default=3, ge=1, le=10)
    delivery_base_backoff_ms: int = Field(default=100, ge=0, le=60_000)
    delivery_max_backoff_ms: int = Field(default=1_000, ge=0, le=60_000)
    delivery_failure_threshold: int = Field(default=5, ge=1, le=100)
    delivery_cooldown_ms: int = Field(default=30_000, ge=0, le=600_000)
    delivery_quote_cache_ttl_seconds: int = Field(default=60, ge=1, le=86_400)

    # Assistant. Absent endpoint means the offline mock provider, which is the
    # deterministic default the tests and a fresh checkout rely on.
    ai_endpoint_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    ai_timeout_ms: int = Field(default=10_000, ge=100, le=120_000)
    ai_max_attempts: int = Field(default=2, ge=1, le=10)
    ai_max_tokens: int = Field(default=400, ge=1, le=100_000)
    ai_max_input_chars: int = Field(default=4_000, ge=100, le=1_000_000)
    ai_cache_ttl_seconds: int = Field(default=300, ge=1, le=86_400)

    # Absent means the scrape endpoint is not exposed at all.
    metrics_token: str | None = Field(default=None, min_length=16)

    shutdown_grace_period_ms: int = Field(default=10_000, ge=0, le=300_000)
    shutdown_timeout_ms: int = Field(default=15_000, ge=1, le=300_000)

    # Absent means each dependency picks its own stand-in exactly as it always
    # has (a mock AI provider, a stub delivery transport, a real cache backed
    # by Redis). `offline` forces every stand-in at once, ignoring the
    # settings above; `live` is the same as leaving it unset.
    infra_profile: Literal["offline", "live"] | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            lowered = value.strip().lower()
            return _LOG_LEVEL_ALIASES.get(lowered, lowered)
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Accepts both the comma-separated and the JSON-array spellings.

        The sibling deployment is configured with a plain comma-separated list,
        so the same ``.env`` file has to drive either implementation; a JSON
        array is still honoured for anything that generates one.
        """
        if not isinstance(value, str):
            return value

        text = value.strip()
        if text.startswith("["):
            try:
                decoded = json.loads(text)
            except ValueError as error:
                message = "cors_origins is neither a JSON array nor a comma-separated list"
                raise ValueError(message) from error
            return decoded

        return [origin.strip() for origin in text.split(",") if origin.strip()]

    @field_validator("database_url")
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        """Accepts a plain PostgreSQL URL and returns an asyncpg one.

        The same connection string has to work for both backends, so the driver
        prefix is added here rather than demanded from the operator. The
        ``schema`` parameter is dropped because asyncpg rejects unknown DSN
        options; the default search path resolves to the same schema.
        """
        parts = urlsplit(value)
        if parts.scheme not in _ACCEPTED_DB_SCHEMES:
            message = f"database_url must be a PostgreSQL URL, got scheme {parts.scheme!r}"
            raise ValueError(message)

        query = [(key, item) for key, item in parse_qsl(parts.query) if key != "schema"]
        return urlunsplit(
            (_ASYNC_DRIVER, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    @field_validator("redis_url", "mongodb_url")
    @classmethod
    def _require_url(cls, value: str, info: ValidationInfo) -> str:
        if not urlsplit(value).scheme:
            message = f"{info.field_name} must be an absolute URL"
            raise ValueError(message)
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def allows_any_origin(self) -> bool:
        return "*" in self.cors_origins


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached because reading and validating the environment repeatedly would let
    two parts of the process disagree about configuration.
    """
    return Settings()
