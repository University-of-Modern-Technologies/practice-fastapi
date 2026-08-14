"""Event log behaviour, driven against an in-memory collection double."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Self

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.settings import Settings
from app.events.connection import (
    EVENT_STORE_READINESS_CHECK_NAME,
    EventStore,
    create_event_store_readiness_check,
)
from app.events.model import (
    ACTOR_HISTORY_INDEX,
    ENTITY_HISTORY_INDEX,
    EVENT_TYPE_INDEX,
    RETENTION_INDEX,
    SECONDS_PER_DAY,
    ensure_indexes,
)
from app.events.sanitize import REDACTED
from app.events.service import EventStoreService, EventStoreUnavailableError
from app.events.types import (
    DomainEvent,
    DomainEventCollection,
    EntityHistoryQuery,
    EventSearchQuery,
    NoopPublisher,
)
from app.factory import create_app
from app.health.lifecycle import service_lifecycle

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _matches(document: dict[str, Any], spec: dict[str, Any]) -> bool:
    for field, expected in spec.items():
        actual = document.get(field)
        if isinstance(expected, dict):
            if "$gte" in expected and actual < expected["$gte"]:
                return False
            if "$lte" in expected and actual > expected["$lte"]:
                return False
        elif actual != expected:
            return False
    return True


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents
        self._skip = 0
        self._limit: int | None = None
        self.sorted_by: list[tuple[str, int]] = []

    def sort(self, key_or_list: Any) -> Self:
        self.sorted_by = list(key_or_list)
        for field, direction in reversed(self.sorted_by):
            self._documents.sort(key=lambda item: item[field], reverse=direction < 0)
        return self

    def skip(self, skip: int) -> Self:
        self._skip = skip
        return self

    def limit(self, limit: int) -> Self:
        self._limit = limit
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:  # noqa: ARG002
        window = self._documents[self._skip :]
        return window if self._limit is None else window[: self._limit]


class _IndexKeySpecsConflictError(Exception):
    """What the server answers when a name is reused for another definition."""

    code = 86


class FakeCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.indexes: list[tuple[list[tuple[str, int]], dict[str, Any]]] = []
        self.dropped: list[str] = []
        self.last_cursor: FakeCursor | None = None

    async def insert_one(self, document: Any) -> Any:
        stored = {"_id": f"id-{len(self.documents) + 1}", **dict(document)}
        self.documents.append(stored)
        return stored

    def find(self, spec: Any) -> FakeCursor:
        cursor = FakeCursor([item for item in self.documents if _matches(item, dict(spec))])
        self.last_cursor = cursor
        return cursor

    async def count_documents(self, spec: Any) -> int:
        return len([item for item in self.documents if _matches(item, dict(spec))])

    async def create_index(self, keys: Any, **kwargs: Any) -> str:
        name: str = kwargs.get("name", "")
        existing = self._by_name(name)
        if existing is not None and existing[0] != list(keys):
            raise _IndexKeySpecsConflictError
        self.indexes.append((list(keys), kwargs))
        return name

    async def drop_index(self, index_or_name: str) -> None:
        self.indexes = [item for item in self.indexes if item[1].get("name") != index_or_name]
        self.dropped.append(index_or_name)

    def _by_name(self, name: str) -> tuple[list[tuple[str, int]], dict[str, Any]] | None:
        return next((item for item in self.indexes if item[1].get("name") == name), None)


class BrokenCollection(FakeCollection):
    async def insert_one(self, document: Any) -> Any:  # noqa: ARG002
        message = "event store is unreachable"
        raise ConnectionError(message)


class FakeSource:
    def __init__(self, collection: DomainEventCollection | None) -> None:
        self._collection = collection

    @property
    def collection(self) -> DomainEventCollection | None:
        return self._collection


@pytest.fixture
def collection() -> FakeCollection:
    return FakeCollection()


@pytest.fixture
def store(collection: FakeCollection) -> EventStoreService:
    return EventStoreService(FakeSource(collection))


def _event(**overrides: Any) -> DomainEvent:
    defaults: dict[str, Any] = {
        "event_type": "contact.created",
        "entity_type": "contact",
        "entity_id": "c-1",
        "actor_id": "u-1",
        "request_id": "r-1",
    }
    return DomainEvent(**{**defaults, **overrides})


async def test_append_persists_the_event(
    store: EventStoreService,
    collection: FakeCollection,
) -> None:
    await store.append(_event(payload={"email": "user@example.com"}))

    assert len(collection.documents) == 1
    stored = collection.documents[0]
    # camelCase on the wire: the collection is shared, and two spellings of the
    # same field in one collection is two incompatible schemas.
    assert stored["eventType"] == "contact.created"
    assert stored["entityType"] == "contact"
    assert stored["entityId"] == "c-1"
    assert stored["actorId"] == "u-1"
    assert stored["requestId"] == "r-1"
    assert "event_type" not in stored
    assert stored["payload"] == {"email": "user@example.com"}


async def test_append_stamps_the_moment_when_the_caller_did_not(
    store: EventStoreService,
    collection: FakeCollection,
) -> None:
    await store.append(_event())

    assert collection.documents[0]["occurredAt"].tzinfo is not None


async def test_append_keeps_an_explicit_timestamp(
    store: EventStoreService,
    collection: FakeCollection,
) -> None:
    await store.append(_event(occurred_at=NOW))

    assert collection.documents[0]["occurredAt"] == NOW


async def test_append_redacts_secrets_from_the_payload(
    store: EventStoreService,
    collection: FakeCollection,
) -> None:
    await store.append(_event(payload={"email": "a@b.c", "password": "hunter2"}))

    assert collection.documents[0]["payload"] == {"email": "a@b.c", "password": REDACTED}


@pytest.mark.parametrize(
    "invalid",
    [
        {"event_type": ""},
        {"entity_type": "   "},
        {"entity_id": ""},
        {"entity_type": "x" * 65},
        {"actor_id": "x" * 129},
    ],
)
async def test_a_malformed_event_is_dropped(
    store: EventStoreService,
    collection: FakeCollection,
    invalid: dict[str, Any],
) -> None:
    await store.append(_event(**invalid))

    assert collection.documents == []


async def test_append_never_raises_when_the_write_fails() -> None:
    store = EventStoreService(FakeSource(BrokenCollection()))

    # A committed business transaction must not be reported as failed because
    # its history could not be recorded.
    await store.append(_event())


async def test_append_never_raises_when_the_store_is_absent() -> None:
    store = EventStoreService(FakeSource(None))

    await store.append(_event())


async def test_reads_fail_loudly_when_the_store_is_absent() -> None:
    store = EventStoreService(FakeSource(None))

    with pytest.raises(EventStoreUnavailableError) as failure:
        await store.list_by_entity(EntityHistoryQuery("contact", "c-1", 1, 20))

    assert failure.value.status_code == 503
    assert failure.value.code == "EVENT_STORE_UNAVAILABLE"


async def test_list_by_entity_returns_the_pagination_envelope(
    store: EventStoreService,
) -> None:
    for index in range(3):
        await store.append(_event(occurred_at=NOW + timedelta(minutes=index)))
    await store.append(_event(entity_id="c-2"))

    result = await store.list_by_entity(EntityHistoryQuery("contact", "c-1", 1, 2))

    assert result.page == 1
    assert result.page_size == 2
    assert result.total == 3
    assert len(result.items) == 2
    # Newest first.
    assert result.items[0].occurred_at == NOW + timedelta(minutes=2)
    assert result.items[0].id == "id-3"


async def test_list_by_entity_skips_to_the_requested_page(
    store: EventStoreService,
    collection: FakeCollection,  # noqa: ARG001
) -> None:
    for index in range(3):
        await store.append(_event(occurred_at=NOW + timedelta(minutes=index)))

    result = await store.list_by_entity(EntityHistoryQuery("contact", "c-1", 2, 2))

    assert result.total == 3
    assert len(result.items) == 1
    assert result.items[0].occurred_at == NOW


async def test_search_filters_by_event_type_and_actor(store: EventStoreService) -> None:
    await store.append(_event(event_type="contact.created", actor_id="u-1", occurred_at=NOW))
    await store.append(_event(event_type="contact.updated", actor_id="u-1", occurred_at=NOW))
    await store.append(_event(event_type="contact.created", actor_id="u-2", occurred_at=NOW))

    result = await store.search(
        EventSearchQuery(page=1, page_size=20, event_type="contact.created", actor_id="u-1")
    )

    assert result.total == 1
    assert result.items[0].actor_id == "u-1"


async def test_search_filters_by_a_time_window(store: EventStoreService) -> None:
    await store.append(_event(occurred_at=NOW - timedelta(days=2)))
    await store.append(_event(occurred_at=NOW))
    await store.append(_event(occurred_at=NOW + timedelta(days=2)))

    result = await store.search(
        EventSearchQuery(
            page=1,
            page_size=20,
            date_from=NOW - timedelta(days=1),
            date_to=NOW + timedelta(days=1),
        )
    )

    assert result.total == 1
    assert result.items[0].occurred_at == NOW


async def test_reads_break_ties_on_the_document_id(
    store: EventStoreService,
    collection: FakeCollection,
) -> None:
    await store.append(_event(occurred_at=NOW))

    await store.list_by_entity(EntityHistoryQuery("contact", "c-1", 1, 20))

    assert collection.last_cursor is not None
    assert collection.last_cursor.sorted_by == [("occurredAt", -1), ("_id", -1)]


async def test_indexes_cover_history_search_and_retention(collection: FakeCollection) -> None:
    await ensure_indexes(collection, retention_days=90)

    by_name = {options["name"]: (keys, options) for keys, options in collection.indexes}

    assert by_name[EVENT_TYPE_INDEX][0] == [("eventType", 1)]
    assert by_name[ENTITY_HISTORY_INDEX][0] == [
        ("entityType", 1),
        ("entityId", 1),
        ("occurredAt", -1),
    ]
    assert by_name[ACTOR_HISTORY_INDEX][0] == [("actorId", 1), ("occurredAt", -1)]
    assert by_name[RETENTION_INDEX][0] == [("occurredAt", 1)]
    assert by_name[RETENTION_INDEX][1]["expireAfterSeconds"] == 90 * SECONDS_PER_DAY


async def test_an_outdated_index_definition_is_replaced_rather_than_skipped(
    collection: FakeCollection,
) -> None:
    """A rejected create would otherwise skip every index queued behind it."""
    await collection.create_index([("entity_type", 1)], name=ENTITY_HISTORY_INDEX)

    await ensure_indexes(collection, retention_days=90)

    assert ENTITY_HISTORY_INDEX in collection.dropped
    by_name = {options["name"]: keys for keys, options in collection.indexes}
    assert by_name[ENTITY_HISTORY_INDEX] == [
        ("entityType", 1),
        ("entityId", 1),
        ("occurredAt", -1),
    ]
    # The indexes queued after the conflicting one still got created.
    assert RETENTION_INDEX in by_name
    assert ACTOR_HISTORY_INDEX in by_name


def test_the_default_publisher_does_nothing() -> None:
    # Domain modules depend on the protocol, so a service built without the
    # fan-out infrastructure still has something to call.
    NoopPublisher().publish(_event())


async def test_the_store_probe_is_critical(settings: Settings) -> None:
    """An instance that cannot reach the store loses the event log silently.

    Reporting that as a mere degradation would leave the instance in rotation,
    serving traffic it can only half-record. The probe is therefore critical, and
    the default of `ReadinessCheck` is relied on rather than restated.
    """
    check = create_event_store_readiness_check(EventStore(settings))

    assert check.name == EVENT_STORE_READINESS_CHECK_NAME
    assert check.critical is True


async def test_an_unreachable_store_takes_the_instance_out_of_rotation(
    settings: Settings,
) -> None:
    """End to end: a store that does not answer yields 503, not a 200."""
    store = EventStore(settings)  # never connected, so the ping cannot succeed
    app: FastAPI = create_app(
        settings,
        readiness_checks=[create_event_store_readiness_check(store)],
    )
    service_lifecycle.reset()
    service_lifecycle.mark_started()

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as probe:
        response = await probe.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"][0]["name"] == EVENT_STORE_READINESS_CHECK_NAME
    assert body["checks"][0]["critical"] is True
