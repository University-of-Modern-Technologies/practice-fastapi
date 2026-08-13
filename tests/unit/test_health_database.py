from __future__ import annotations

from pathlib import Path
from typing import Any

from app.health.database import create_database_readiness_check
from app.health.readiness import run_readiness_checks

FIXTURE_MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "schema_check_migrations"
)
HEAD_REVISION = "0001_fixture"


class _FakeResult:
    def __init__(self, value: str | None) -> None:
        self._value = value

    def scalar(self) -> str | None:
        return self._value


class _FakeConnection:
    def __init__(self, version: str | None, *, connect_fails: bool = False) -> None:
        self._version = version
        self._connect_fails = connect_fails

    async def __aenter__(self) -> _FakeConnection:
        if self._connect_fails:
            message = "connect ECONNREFUSED"
            raise ConnectionError(message)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def execute(self, *_args: Any, **_kwargs: Any) -> _FakeResult:
        return _FakeResult(self._version)


class _FakeEngine:
    def __init__(self, version: str | None, *, connect_fails: bool = False) -> None:
        self._version = version
        self._connect_fails = connect_fails

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self._version, connect_fails=self._connect_fails)


class _FakeDatabase:
    """Stands in for `app.db.session.Database`: only `ping` and `engine` are used."""

    def __init__(self, version: str | None, *, connect_fails: bool = False) -> None:
        self.engine = _FakeEngine(version, connect_fails=connect_fails)
        self._connect_fails = connect_fails

    async def ping(self) -> None:
        if self._connect_fails:
            message = "connect ECONNREFUSED"
            raise ConnectionError(message)


async def test_reports_up_as_a_single_database_entry_when_both_sub_checks_pass() -> None:
    database = _FakeDatabase(HEAD_REVISION)
    check = create_database_readiness_check(database, FIXTURE_MIGRATIONS_DIR)  # type: ignore[arg-type]

    (result,) = await run_readiness_checks([check])

    assert result.name == "database"
    assert result.status == "up"
    assert result.critical is True


async def test_fails_as_database_when_the_connection_is_unreachable() -> None:
    database = _FakeDatabase(HEAD_REVISION, connect_fails=True)
    check = create_database_readiness_check(database, FIXTURE_MIGRATIONS_DIR)  # type: ignore[arg-type]

    (result,) = await run_readiness_checks([check])

    assert result.name == "database"
    assert result.status == "down"


async def test_fails_as_database_when_the_newest_migration_was_never_applied() -> None:
    database = _FakeDatabase("some-older-revision")
    check = create_database_readiness_check(database, FIXTURE_MIGRATIONS_DIR)  # type: ignore[arg-type]

    (result,) = await run_readiness_checks([check])

    assert result.name == "database"
    assert result.status == "down"
    assert "schema" in repr(result.error)
