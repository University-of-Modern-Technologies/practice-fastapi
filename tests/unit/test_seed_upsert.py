"""Seed upserts preserve deterministic fixture timestamps on rerun."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection

from scripts.seed import upsert


class RecordingConnection:
    """Collects the Core statement without requiring a database."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> None:
        self.statements.append(statement)


PG_DIALECT = cast("Any", postgresql).dialect()

TABLE = Table(
    "seed_rows",
    MetaData(),
    Column("id", Integer, primary_key=True),
    Column("name", String, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


async def test_an_explicit_fixture_timestamp_is_restored_on_conflict() -> None:
    connection = RecordingConnection()
    fixture_time = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    await upsert(
        cast("AsyncConnection", connection),
        TABLE,
        [{"id": 1, "name": "fixture", "updated_at": fixture_time}],
        conflict=["id"],
        update=["name"],
    )

    sql = str(connection.statements[0].compile(dialect=PG_DIALECT))
    assert "updated_at = excluded.updated_at" in sql


async def test_an_operational_upsert_keeps_the_database_action_time() -> None:
    connection = RecordingConnection()

    await upsert(
        cast("AsyncConnection", connection),
        TABLE,
        [{"id": 1, "name": "operational"}],
        conflict=["id"],
        update=["name"],
    )

    sql = str(connection.statements[0].compile(dialect=PG_DIALECT))
    assert "updated_at = now()" in sql


async def test_a_batch_cannot_mix_explicit_and_operational_timestamps() -> None:
    connection = RecordingConnection()

    with pytest.raises(
        ValueError,
        match="All rows in one upsert batch must either include updated_at or omit it",
    ):
        await upsert(
            cast("AsyncConnection", connection),
            TABLE,
            [
                {"id": 1, "name": "fixture", "updated_at": datetime(2026, 1, 1, tzinfo=UTC)},
                {"id": 2, "name": "operational"},
            ],
            conflict=["id"],
            update=["name"],
        )

    assert connection.statements == []
