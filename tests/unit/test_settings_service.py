"""Settings rules: defaults, caching, and what a delete actually means."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.db.models.audit import AuditLog
from app.db.models.setting import OrganizationSetting
from app.modules.settings.cache_keys import setting_value_key, settings_list_key
from app.modules.settings.schemas import SettingOut, UpsertSettingRequest
from app.modules.settings.service import SettingsService, to_setting_out
from app.modules.settings.types import SettingsAccess

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)
ACTOR_ID = uuid.uuid4()
ACCESS = SettingsAccess(actor_id=ACTOR_ID, ip_address="203.0.113.7")
KEY = "organization.name"


class FakeScalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return list(self._values)


class FakeResult:
    def __init__(self, values: list[Any] | None = None) -> None:
        self._values = values or []

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._values)

    def scalar_one_or_none(self) -> Any:
        return self._values[0] if self._values else None


class FakeSession:
    """A scripted stand-in: each call pops the next prepared answer."""

    def __init__(self) -> None:
        self.execute_queue: list[list[Any]] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.executions = 0

    async def execute(self, statement: Any) -> FakeResult:  # noqa: ARG002
        self.executions += 1
        return FakeResult(self.execute_queue.pop(0) if self.execute_queue else [])

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def delete(self, instance: Any) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        # Stands in for the column defaults the database would apply.
        for instance in self.added:
            if isinstance(instance, OrganizationSetting):
                instance.created_at = instance.created_at or NOW
                instance.updated_at = instance.updated_at or NOW
            elif isinstance(instance, AuditLog):
                instance.id = instance.id or uuid.uuid4()
                instance.created_at = instance.created_at or NOW

    @property
    def audit_entries(self) -> list[AuditLog]:
        return [row for row in self.added if isinstance(row, AuditLog)]

    @property
    def rows(self) -> list[OrganizationSetting]:
        return [row for row in self.added if isinstance(row, OrganizationSetting)]


class FakeCache:
    """An in-memory cache that also counts what was asked of it."""

    def __init__(self) -> None:
        self.entries: dict[str, Any] = {}
        self.reads: list[str] = []
        self.dropped: list[str] = []

    async def get(self, key: str) -> Any | None:
        self.reads.append(key)
        return self.entries.get(key)

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:  # noqa: ARG002
        self.entries[key] = value

    async def delete(self, keys: str | Sequence[str]) -> None:
        targets = [keys] if isinstance(keys, str) else list(keys)
        for key in targets:
            self.dropped.append(key)
            self.entries.pop(key, None)


class BrokenCache:
    """Every operation fails, the way an unreachable backend would."""

    async def get(self, key: str) -> Any | None:
        raise ConnectionError(key)

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:  # noqa: ARG002
        raise ConnectionError(key)

    async def delete(self, keys: str | Sequence[str]) -> None:
        raise ConnectionError(str(keys))


def changes_of(entry: AuditLog) -> dict[str, Any]:
    """The recorded change, once it is known to be there."""
    assert entry.changes is not None
    return entry.changes


def make_row(**overrides: Any) -> OrganizationSetting:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "key": KEY,
        "value": "Acme",
        "description": None,
        "updated_by_id": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return OrganizationSetting(**values)


def make_service(session: FakeSession, cache: Any = None) -> SettingsService:
    return SettingsService(cast("AsyncSession", session), cache, 300)


def test_a_key_without_a_row_is_served_from_the_registry() -> None:
    dto = to_setting_out(KEY, None)

    assert dto.value == "Training CRM"
    assert dto.source == "default"
    assert dto.updated_at is None
    assert dto.description == "Display name of the organization."


def test_a_stored_row_reports_where_its_value_came_from() -> None:
    dto = to_setting_out(KEY, make_row(updated_by_id=ACTOR_ID))

    assert dto.value == "Acme"
    assert dto.source == "database"
    assert dto.updated_by_id == ACTOR_ID
    assert dto.updated_at == "2026-08-12T15:23:45.123Z"


def test_a_row_written_before_a_declaration_was_tightened_still_reads() -> None:
    dto = to_setting_out(KEY, make_row(value={"legacy": True}))

    assert dto.value == "Training CRM"


async def test_reading_an_undeclared_key_never_reaches_the_database() -> None:
    session = FakeSession()
    service = make_service(session)

    with pytest.raises(AppError) as error:
        await service.get_by_key("organization.unknown")

    assert error.value.code == "UNKNOWN_SETTING_KEY"
    assert session.executions == 0


async def test_a_second_read_of_the_same_key_is_served_from_the_cache() -> None:
    session = FakeSession()
    session.execute_queue = [[make_row()]]
    cache = FakeCache()
    service = make_service(session, cache)

    first = await service.get_by_key(KEY)
    second = await service.get_by_key(KEY)

    assert first == second
    assert session.executions == 1
    assert setting_value_key(KEY) in cache.entries


async def test_a_cache_entry_of_an_older_shape_is_treated_as_a_miss() -> None:
    session = FakeSession()
    session.execute_queue = [[make_row()]]
    cache = FakeCache()
    cache.entries[setting_value_key(KEY)] = {"key": KEY, "legacy": True}
    service = make_service(session, cache)

    dto = await service.get_by_key(KEY)

    # Reading it as current would publish a shape the client no longer knows.
    assert dto.value == "Acme"
    assert session.executions == 1


async def test_an_unreachable_cache_slows_a_read_down_but_never_fails_it() -> None:
    session = FakeSession()
    session.execute_queue = [[make_row()]]
    service = make_service(session, BrokenCache())

    dto = await service.get_by_key(KEY)

    assert dto.value == "Acme"


async def test_the_listing_covers_every_declared_key() -> None:
    session = FakeSession()
    session.execute_queue = [[make_row()]]
    cache = FakeCache()
    service = make_service(session, cache)

    items = await service.list()

    assert [item.key for item in items] == [
        "orders.numberPrefix",
        "organization.defaultCurrency",
        "organization.name",
        "warehouse.defaultCode",
    ]
    # A declared key without a row is still listed, showing its default.
    assert [item.source for item in items] == ["default", "default", "database", "default"]
    assert settings_list_key() in cache.entries


async def test_a_typed_accessor_falls_back_to_the_declared_default() -> None:
    session = FakeSession()
    service = make_service(session)

    # The orders module reads this one at boot; a gap here would stop it.
    assert await service.get("warehouse.defaultCode") == "CENTRAL"


async def test_writing_a_value_of_the_wrong_shape_stores_nothing() -> None:
    session = FakeSession()
    service = make_service(session)

    with pytest.raises(AppError) as error:
        await service.upsert(
            ACCESS, "organization.defaultCurrency", UpsertSettingRequest(value="EURO")
        )

    assert error.value.code == "INVALID_SETTING_VALUE"
    assert session.added == []


async def test_writing_an_undeclared_key_stores_nothing() -> None:
    session = FakeSession()
    service = make_service(session)

    with pytest.raises(AppError) as error:
        await service.upsert(ACCESS, "organization.unknown", UpsertSettingRequest(value="x"))

    assert error.value.code == "UNKNOWN_SETTING_KEY"
    assert session.added == []


async def test_a_first_write_creates_the_row_and_stamps_its_author() -> None:
    session = FakeSession()
    cache = FakeCache()
    service = make_service(session, cache)

    dto = await service.upsert(ACCESS, KEY, UpsertSettingRequest(value="  Acme  "))

    assert dto.value == "Acme"
    assert dto.source == "database"
    row = session.rows[0]
    assert row.updated_by_id == ACTOR_ID
    assert row.description == "Display name of the organization."
    entry = session.audit_entries[0]
    assert entry.action == "setting.updated"
    assert entry.entity_type == "organization_setting"
    assert entry.ip_address == "203.0.113.7"
    assert changes_of(entry)["before"] is None
    assert changes_of(entry)["after"]["value"] == "Acme"


async def test_a_write_drops_exactly_the_entries_it_invalidated() -> None:
    session = FakeSession()
    session.execute_queue = [[make_row()]]
    cache = FakeCache()
    cache.entries[setting_value_key(KEY)] = {"stale": True}
    cache.entries[settings_list_key()] = [{"stale": True}]
    service = make_service(session, cache)

    await service.upsert(ACCESS, KEY, UpsertSettingRequest(value="Acme"))

    assert cache.dropped == [setting_value_key(KEY), settings_list_key()]
    assert cache.entries == {}


async def test_a_second_write_updates_the_existing_row() -> None:
    row = make_row(value="Acme")
    session = FakeSession()
    session.execute_queue = [[row]]
    service = make_service(session)

    dto = await service.upsert(
        ACCESS, KEY, UpsertSettingRequest(value="Acme Corp", description="The trading name")
    )

    assert session.rows == []  # nothing new was inserted
    assert row.value == "Acme Corp"
    assert row.description == "The trading name"
    assert dto.description == "The trading name"
    assert changes_of(session.audit_entries[0])["before"]["value"] == "Acme"


async def test_resetting_a_key_that_has_no_row_is_a_not_found() -> None:
    session = FakeSession()
    service = make_service(session)

    with pytest.raises(NotFoundError) as error:
        await service.remove(ACCESS, KEY)

    assert error.value.code == "SETTING_NOT_FOUND"


async def test_resetting_a_key_restores_the_default_rather_than_erasing_it() -> None:
    row = make_row(value="Acme")
    session = FakeSession()
    session.execute_queue = [[row]]
    cache = FakeCache()
    service = make_service(session, cache)

    await service.remove(ACCESS, KEY)

    assert session.deleted == [row]
    entry = session.audit_entries[0]
    assert entry.action == "setting.deleted"
    assert changes_of(entry)["before"]["value"] == "Acme"
    # The key keeps existing — it is declared, not created — so what the trail
    # records after the reset is the registry default, not a gap.
    assert changes_of(entry)["after"]["value"] == "Training CRM"
    assert changes_of(entry)["after"]["source"] == "default"
    assert cache.dropped == [setting_value_key(KEY), settings_list_key()]


async def test_a_key_that_was_reset_still_answers_with_its_default() -> None:
    session = FakeSession()  # no row: the reset removed it
    service = make_service(session)

    dto = await service.get_by_key(KEY)

    assert dto.value == "Training CRM"
    assert dto.source == "default"


def test_a_dto_survives_the_round_trip_through_the_cache() -> None:
    dto = to_setting_out(KEY, make_row(updated_by_id=ACTOR_ID))

    restored = SettingOut.model_validate(dto.model_dump(mode="json", by_alias=True))

    assert restored == dto
