"""Settings that decide how the process runs rather than what it does."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.settings import Settings
from app.db.session import Database

BASE = {
    "app_env": "test",
    "database_url": "postgresql://u:p@localhost:5432/crm",
    "jwt_access_secret": "a-secret-that-is-long-enough-here",
    "jwt_refresh_secret": "another-secret-long-enough-here!",
    "redis_url": "redis://localhost:6379",
    "mongodb_url": "mongodb://localhost:27017/events",
}


def build(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def test_a_blank_environment_value_means_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in BASE.items():
        monkeypatch.setenv(name.upper(), value)
    for name in ("CACHE_TTL_SECONDS", "METRICS_TOKEN", "DELIVERY_BASE_URL", "CORS_ORIGINS"):
        monkeypatch.setenv(name, "")

    settings = Settings(_env_file=None)

    assert settings.cache_ttl_seconds == 300
    assert settings.metrics_token is None
    assert settings.delivery_base_url is None
    assert settings.cors_origins == ["http://localhost:3000"]


def test_no_proxy_is_trusted_by_default() -> None:
    assert build().trusted_proxies == []


def test_trusted_proxies_take_addresses_and_networks() -> None:
    settings = build(trusted_proxies="172.16.0.0/12, 10.0.0.1,fd00::/8")

    assert settings.trusted_proxies == ["172.16.0.0/12", "10.0.0.1", "fd00::/8"]


@pytest.mark.parametrize("value", ["*", "nginx", "10.0.0.0/33"])
def test_a_trusted_proxy_must_be_an_address_or_a_network(value: str) -> None:
    with pytest.raises(ValidationError, match="trusted_proxies"):
        build(trusted_proxies=value)


@pytest.mark.parametrize(
    ("grace_ms", "seconds"), [(10_000, 10), (1_500, 2), (999, 1), (1, 1), (0, 0)]
)
def test_the_grace_period_is_what_the_server_waits_for_in_flight_requests(
    grace_ms: int, seconds: int
) -> None:
    """The grace period, not the overall timeout, as in the sibling backend."""
    settings = build(shutdown_grace_period_ms=grace_ms, shutdown_timeout_ms=15_000)

    assert settings.graceful_shutdown_seconds == seconds


#: `stop_grace_period` of the API service in compose: past it the container
#: runtime kills the process, so the whole stop has to end earlier.
COMPOSE_STOP_GRACE_PERIOD_MS = 20_000


def test_the_default_stop_ends_before_the_container_is_killed() -> None:
    settings = build()

    budget = settings.shutdown_drain_delay_ms + settings.shutdown_grace_period_ms
    assert budget <= settings.shutdown_timeout_ms < COMPOSE_STOP_GRACE_PERIOD_MS


def test_sql_is_not_logged_unless_asked_for() -> None:
    assert Database(build(app_env="development")).engine.echo is False
    assert Database(build(app_env="development", log_sql=True)).engine.echo is True


def test_sql_is_never_logged_in_production() -> None:
    assert Database(build(app_env="production", log_sql=True)).engine.echo is False
