"""Application configuration.

A single validated model is the only place the process reads the environment.
Anything that fails validation aborts the boot instead of surfacing as a runtime
error deep inside a request.

Values come from three layers, highest priority first: the process environment,
the backend's own ``.env``, and the repository's shared ``.env`` one level up.
"""

from __future__ import annotations

import ipaddress
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from pydantic import Field, ValidationInfo, field_validator, model_validator
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

#: `app/core/settings.py` → the backend folder.
BACKEND_ROOT = Path(__file__).resolve().parents[2]

#: The shared file first and the backend's own second, so the latter wins. The
#: paths are absolute because Alembic, the scripts and the tests each start
#: from a different working directory. A file that does not exist is skipped.
ENV_FILES = (BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env")

# An IPv4 literal rather than `localhost`: on Windows the name resolves to IPv6
# first, and every connection to a storage listening on IPv4 only waits two
# seconds for that attempt to time out.
_DEFAULT_STORAGE_HOST = "127.0.0.1"
_DEFAULT_POSTGRES_PORT = 5432
_DEFAULT_REDIS_PORT = 6379
_DEFAULT_MONGO_PORT = 27017


def _part(values: dict[str, Any], key: str) -> str | None:
    """A raw setting as text, with a blank value treated as absent."""
    value = values.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _credentials(user: str, password: str) -> str:
    return f"{quote(user, safe='')}:{quote(password, safe='')}@"


def _postgres_url(values: dict[str, Any]) -> str | None:
    user = _part(values, "postgres_user")
    password = _part(values, "postgres_password")
    database = _part(values, "postgres_db")
    if user is None or password is None or database is None:
        return None
    host = _part(values, "postgres_host") or _DEFAULT_STORAGE_HOST
    port = _part(values, "postgres_port") or _DEFAULT_POSTGRES_PORT
    return f"postgresql://{_credentials(user, password)}{host}:{port}/{quote(database, safe='')}"


def _redis_url(values: dict[str, Any]) -> str:
    host = _part(values, "redis_host") or _DEFAULT_STORAGE_HOST
    port = _part(values, "redis_port") or _DEFAULT_REDIS_PORT
    return f"redis://{host}:{port}"


def _mongodb_url(values: dict[str, Any]) -> str | None:
    database = _part(values, "mongo_db")
    if database is None:
        return None
    host = _part(values, "mongo_host") or _DEFAULT_STORAGE_HOST
    port = _part(values, "mongo_port") or _DEFAULT_MONGO_PORT
    address = f"{host}:{port}/{quote(database, safe='')}"
    user = _part(values, "mongo_user")
    password = _part(values, "mongo_password")
    if user is None or password is None:
        return f"mongodb://{address}"
    return f"mongodb://{_credentials(user, password)}{address}?authSource=admin"


class Settings(BaseSettings):
    """Validated view of the process environment."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: AppEnv = "development"
    host: str = Field(default="0.0.0.0", min_length=1)
    # `PORT` wins; without it the shared `API_PORT` is used.
    port: int = Field(default=8000, ge=1, le=65_535)
    api_port: int | None = Field(default=None, ge=1, le=65_535)
    log_level: LogLevel = "info"
    # ``NoDecode`` keeps the raw environment string intact. Without it the
    # settings source JSON-decodes a ``list[str]`` field before any validator
    # runs, so the comma-separated form operators actually write would fail the
    # boot with a JSON parse error. The validator below accepts both spellings.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    json_body_limit_bytes: int = Field(default=1_048_576, ge=1_024, le=67_108_864)
    # Addresses or CIDR networks of the reverse proxies in front of the API.
    # Only a request that arrives from one of them has its X-Forwarded-For
    # believed; empty means the peer address is the client, whatever it says.
    trusted_proxies: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Logs every SQL statement together with its parameters; never in production.
    log_sql: bool = False

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

    # Telephony. Absent base URL means the built-in offline stub, so a fresh
    # checkout imports a journal without a carrier account.
    call_provider_base_url: str | None = None
    call_provider_api_key: str | None = None
    call_provider_timeout_ms: int = Field(default=5_000, ge=100, le=120_000)
    call_provider_max_attempts: int = Field(default=3, ge=1, le=10)
    call_provider_backoff_ms: int = Field(default=200, ge=0, le=60_000)
    call_sync_batch_size: int = Field(default=100, ge=1, le=500)

    # Absent means the scrape endpoint is not exposed at all.
    metrics_token: str | None = Field(default=None, min_length=16)

    # Serves `/api/docs` and `/api/openapi.json`. Absent means on everywhere
    # except production; the validator below fills it in from `app_env`.
    api_docs_enabled: bool = True

    # The parts a storage address is assembled from when its full URL is not
    # given. They live in the shared `.env`, next to the containers they name.
    postgres_host: str = Field(default=_DEFAULT_STORAGE_HOST, min_length=1)
    postgres_port: int = Field(default=_DEFAULT_POSTGRES_PORT, ge=1, le=65_535)
    postgres_user: str | None = None
    postgres_password: str | None = Field(default=None, repr=False)
    postgres_db: str | None = None
    redis_host: str = Field(default=_DEFAULT_STORAGE_HOST, min_length=1)
    redis_port: int = Field(default=_DEFAULT_REDIS_PORT, ge=1, le=65_535)
    mongo_host: str = Field(default=_DEFAULT_STORAGE_HOST, min_length=1)
    mongo_port: int = Field(default=_DEFAULT_MONGO_PORT, ge=1, le=65_535)
    mongo_user: str | None = None
    mongo_password: str | None = Field(default=None, repr=False)
    mongo_db: str | None = None

    shutdown_grace_period_ms: int = Field(default=10_000, ge=0, le=300_000)
    shutdown_timeout_ms: int = Field(default=15_000, ge=1, le=300_000)

    # Absent means each dependency picks its own stand-in exactly as it always
    # has (a mock AI provider, a stub delivery transport, a real cache backed
    # by Redis). `offline` forces every stand-in at once, ignoring the
    # settings above; `live` is the same as leaving it unset.
    infra_profile: Literal["offline", "live"] | None = None

    @model_validator(mode="before")
    @classmethod
    def _assemble_from_parts(cls, data: Any) -> Any:
        """Fills in the port, the storage URLs and the docs switch not given.

        An explicit URL always wins. When the parts a URL needs are missing the
        field is left unset, so validation names the missing URL instead of a
        connection failing later against a half-built address.
        """
        if not isinstance(data, dict):
            return data

        # A blank value means "not set", so the field's default applies: `KEY=`
        # behaves like a commented-out line, as it does in the sibling backend.
        # It still outranks the layers below it, which is how a blank variable
        # in the process clears a value one of the files sets.
        values: dict[str, Any] = {
            key: value
            for key, value in data.items()
            if not (isinstance(value, str) and not value.strip())
        }
        if _part(values, "port") is None and _part(values, "api_port") is not None:
            values["port"] = values["api_port"]

        # The default depends on another field, so it is decided here rather
        # than on the field itself. A blank value counts as absent.
        if _part(values, "api_docs_enabled") is None:
            values["api_docs_enabled"] = _part(values, "app_env") != "production"

        assemblers = (
            ("database_url", _postgres_url),
            ("redis_url", _redis_url),
            ("mongodb_url", _mongodb_url),
        )
        for field, assemble in assemblers:
            if _part(values, field) is None:
                assembled = assemble(values)
                if assembled is None:
                    # A blank value would be reported as a malformed URL.
                    values.pop(field, None)
                else:
                    values[field] = assembled
        return values

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

    @field_validator("trusted_proxies", mode="before")
    @classmethod
    def _split_trusted_proxies(cls, value: object) -> object:
        """A comma-separated list of addresses or networks; nothing else.

        A wildcard is refused on purpose: believing every peer would let any
        client name its own address and so its own rate-limit budget.
        """
        if not isinstance(value, str):
            return value
        entries = [entry.strip() for entry in value.split(",") if entry.strip()]
        for entry in entries:
            try:
                ipaddress.ip_network(entry, strict=False)
            except ValueError as error:
                message = (
                    "trusted_proxies must be a comma-separated list of addresses or CIDR networks"
                )
                raise ValueError(message) from error
        return entries

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

    @property
    def logs_sql(self) -> bool:
        """Whether every statement is logged; never in production."""
        return self.log_sql and not self.is_production

    @property
    def graceful_shutdown_seconds(self) -> int:
        """`SHUTDOWN_TIMEOUT_MS` in the whole seconds the server counts in.

        Rounded up, never down to zero: a timeout under a second would
        otherwise cut every in-flight request off the moment a stop begins.
        """
        return max(1, math.ceil(self.shutdown_timeout_ms / 1000))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached because reading and validating the environment repeatedly would let
    two parts of the process disagree about configuration.
    """
    return Settings()
