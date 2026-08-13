"""Scenario 1 — the migrations, applied to a real PostgreSQL server.

A migration that only works on an empty file, or only on the machine of whoever
wrote it, fails here rather than in production. The checks are deliberately
about the *shape* of the schema — tables, native enum types, the constraints the
domain rules lean on — because those are what the application code assumes and
what a future migration can quietly break.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.db.base import Base
from tests.integration.conftest import asyncpg_url, run_alembic

#: The four vocabularies that exist as native PostgreSQL types.
ENUM_TYPES = ("PermissionScope", "DealStage", "OrderStatus", "StockMovementType")


def _query(url: str, sql: str) -> list[tuple[object, ...]]:
    async def run() -> list[tuple[object, ...]]:
        engine = create_async_engine(asyncpg_url(url), poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                result = await connection.execute(text(sql))
                return [tuple(row) for row in result]
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _table_names(url: str) -> set[str]:
    rows = _query(
        url,
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'",
    )
    return {str(name) for (name,) in rows}


def _enum_labels(url: str, type_name: str) -> list[str]:
    rows = _query(
        url,
        "SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
        f"WHERE typname = '{type_name}' ORDER BY enumsortorder",
    )
    return [str(label) for (label,) in rows]


def test_upgrade_builds_the_schema_the_models_describe(scratch_database: str) -> None:
    run_alembic("upgrade", "head", database_url=scratch_database)

    tables = _table_names(scratch_database)
    assert "alembic_version" in tables
    # Every mapped table exists, and nothing extra was left behind: a table the
    # models no longer describe is a migration somebody forgot to finish.
    assert set(Base.metadata.tables) == tables - {"alembic_version"}


def test_the_enum_types_are_native_and_uppercase(scratch_database: str) -> None:
    run_alembic("upgrade", "head", database_url=scratch_database)

    for type_name in ENUM_TYPES:
        labels = _enum_labels(scratch_database, type_name)
        assert labels, f"{type_name} was not created as a native enum type"
        # The labels are what both backends write into the column; a lowercase
        # one here would only surface as a client-side bug much later.
        assert labels == [label.upper() for label in labels]

    assert _enum_labels(scratch_database, "OrderStatus") == [
        "DRAFT",
        "CONFIRMED",
        "PAID",
        "FULFILLED",
        "CANCELLED",
    ]


def test_the_stock_invariants_are_enforced_by_the_database(scratch_database: str) -> None:
    """The rules the stock service relies on are constraints, not conventions."""
    run_alembic("upgrade", "head", database_url=scratch_database)

    rows = _query(
        scratch_database,
        "SELECT conname FROM pg_constraint WHERE conrelid = 'stock_levels'::regclass",
    )
    names = {str(name) for (name,) in rows}

    assert any("quantities_non_negative" in name for name in names)
    assert any("reserved_within_on_hand" in name for name in names)


def test_the_migration_can_be_undone_and_reapplied(scratch_database: str) -> None:
    """A migration nobody can roll back is a deployment nobody can abort."""
    run_alembic("upgrade", "head", database_url=scratch_database)
    run_alembic("downgrade", "base", database_url=scratch_database)

    remaining = _table_names(scratch_database) - {"alembic_version"}
    assert remaining == set()
    for type_name in ENUM_TYPES:
        assert _enum_labels(scratch_database, type_name) == []

    run_alembic("upgrade", "head", database_url=scratch_database)
    assert set(Base.metadata.tables) == _table_names(scratch_database) - {"alembic_version"}
