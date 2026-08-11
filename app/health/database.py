"""Composite readiness probe for the primary database.

Splits the single opaque "database" failure into what actually broke: the
network path to Postgres, or a deploy that forgot to run
``alembic upgrade head``. Those are different incidents for whoever is paged,
even though the public payload still reports one ``database`` entry, exactly
as every consumer of this probe already expects.
"""

from __future__ import annotations

from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import Database
from app.health.composite import create_composite_readiness_check
from app.health.readiness import ReadinessCheck

#: `app/health/database.py` → project root → `migrations/`.
_DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class SchemaNotUpToDateError(Exception):
    """The database is reachable but the newest migration was never applied."""

    def __init__(self, expected: str | None, actual: str | None) -> None:
        super().__init__(
            f"Database schema is behind: migration {expected!r} is not applied "
            f"(recorded: {actual!r})"
        )


def _read_head_revision(migrations_dir: Path) -> str | None:
    """The newest revision the code was shipped with, read straight off disk.

    Not cached at import time: a check that answered whatever the process saw
    on its first request would never notice a deploy that added a migration
    without a restart.
    """
    return ScriptDirectory(str(migrations_dir)).get_current_head()


async def _check_schema_applied(engine: AsyncEngine, migrations_dir: Path) -> None:
    expected = _read_head_revision(migrations_dir)
    # Nothing shipped to check against — a checkout without any migration is
    # not this probe's problem to report.
    if expected is None:
        return

    async with engine.connect() as connection:
        current = (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar()

    if current != expected:
        raise SchemaNotUpToDateError(expected, current)


def create_database_readiness_check(
    database: Database, migrations_dir: Path = _DEFAULT_MIGRATIONS_DIR
) -> ReadinessCheck:
    """Reports the database as one entry, backed by two independent probes.

    A connection failure and an unapplied migration are different incidents —
    one is a network or credentials problem, the other is a deploy that never
    ran ``alembic upgrade head`` — and the log line for each says which one it
    was, even though the public payload still reports a single ``database``
    check like it always has.

    ``migrations_dir`` is overridden by tests only, so they can point at a
    fixture instead of this repository's real migration history.
    """
    return create_composite_readiness_check(
        "database",
        [
            ReadinessCheck(name="connection", check=database.ping),
            ReadinessCheck(
                name="schema",
                check=lambda: _check_schema_applied(database.engine, migrations_dir),
            ),
        ],
    )
