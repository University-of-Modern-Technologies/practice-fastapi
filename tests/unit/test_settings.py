from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.settings import Settings

BASE = {
    "app_env": "test",
    "jwt_access_secret": "a-secret-that-is-long-enough-here",
    "jwt_refresh_secret": "another-secret-long-enough-here!",
    "redis_url": "redis://localhost:6379",
    "mongodb_url": "mongodb://localhost:27017/events",
}


def build(**overrides: object) -> Settings:
    return Settings(**{**BASE, **overrides})  # type: ignore[arg-type]


def test_plain_postgres_url_gains_the_async_driver() -> None:
    settings = build(database_url="postgresql://user:pass@localhost:5432/crm")

    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_schema_parameter_is_dropped() -> None:
    settings = build(database_url="postgresql://user:pass@localhost:5432/crm?schema=public")

    assert "schema=" not in settings.database_url
    assert settings.database_url.endswith("/crm")


def test_other_query_parameters_survive() -> None:
    settings = build(
        database_url="postgresql://user:pass@localhost:5432/crm?schema=public&sslmode=require"
    )

    assert "sslmode=require" in settings.database_url


def test_non_postgres_url_is_refused() -> None:
    with pytest.raises(ValidationError):
        build(database_url="mysql://user:pass@localhost:3306/crm")


def test_short_secret_is_refused() -> None:
    with pytest.raises(ValidationError):
        build(database_url="postgresql://u:p@localhost:5432/crm", jwt_access_secret="too-short")


def test_comma_separated_origins_become_a_list() -> None:
    settings = build(
        database_url="postgresql://u:p@localhost:5432/crm",
        cors_origins="http://localhost:3100, http://localhost:5173",
    )

    assert settings.cors_origins == ["http://localhost:3100", "http://localhost:5173"]


@pytest.mark.parametrize(
    "written",
    [
        "http://localhost:3100,http://localhost:5173",
        "http://localhost:3100, http://localhost:5173",
        '["http://localhost:3100", "http://localhost:5173"]',
    ],
)
def test_origins_are_read_from_the_environment_in_either_spelling(
    monkeypatch: pytest.MonkeyPatch, written: str
) -> None:
    """Through the environment, not through a keyword.

    The settings source decodes a list-typed field before any validator sees it,
    so a form that works as a constructor argument can still fail the boot. Both
    spellings an operator may write into `.env` have to survive that path.
    """
    for key, value in BASE.items():
        monkeypatch.setenv(key.upper(), str(value))
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/crm")
    monkeypatch.setenv("CORS_ORIGINS", written)

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["http://localhost:3100", "http://localhost:5173"]


def test_an_origin_list_that_is_neither_spelling_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in BASE.items():
        monkeypatch.setenv(key.upper(), str(value))
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/crm")
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3100')

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(("given", "expected"), [("warn", "warning"), ("fatal", "critical")])
def test_level_names_of_the_sibling_backend_are_understood(given: str, expected: str) -> None:
    settings = build(database_url="postgresql://u:p@localhost:5432/crm", log_level=given)

    assert settings.log_level == expected
