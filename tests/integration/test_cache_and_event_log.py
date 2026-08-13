"""Scenario 6 — the two stores that are allowed to be missing.

Chosen as the sixth scenario because it is the riskiest place in the system:
both of these subsystems are deliberately fail-open, which means every bug in
them is silent by construction. A cache that never stores anything and an event
log that drops every append both look exactly like a healthy system from the
outside — so they are worth exercising against real servers, where a wrong key
prefix or a missing index actually shows.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from redis.asyncio import Redis

from app.cache.client import PrefixedRedis, close_redis_client, create_redis_client
from app.cache.service import CacheService
from app.core.settings import Settings
from app.events.connection import EventStore
from app.events.model import DOMAIN_EVENT_COLLECTION, RETENTION_INDEX
from app.events.service import EventStoreService
from app.events.types import DomainEvent, EntityHistoryQuery, EventSearchQuery

CACHE_TTL_SECONDS = 60


@pytest.fixture
async def cache(
    store_settings: Settings, redis_url: str
) -> AsyncIterator[tuple[CacheService, PrefixedRedis]]:
    """A cache on a key prefix of its own, emptied when the test ends."""
    settings = store_settings.model_copy(update={"redis_url": redis_url})
    client = create_redis_client(settings)
    try:
        await client.ping()
    except Exception as error:
        await close_redis_client(client)
        pytest.skip(f"Redis is not reachable at REDIS_URL: {error!r}")

    service = CacheService(client, settings)
    try:
        yield service, client
    finally:
        await service.invalidate_prefix("")
        await close_redis_client(client)


async def test_a_value_survives_the_round_trip(
    cache: tuple[CacheService, PrefixedRedis],
) -> None:
    service, _ = cache
    payload = {"total": 3, "items": ["a", "b"], "nested": {"ok": True}}

    await service.set("analytics:summary", payload, CACHE_TTL_SECONDS)

    assert await service.get("analytics:summary") == payload
    assert await service.get("analytics:missing") is None


async def test_every_key_carries_the_configured_prefix(
    cache: tuple[CacheService, PrefixedRedis], store_settings: Settings
) -> None:
    service, client = cache
    await service.set("scoped", 1, CACHE_TTL_SECONDS)

    raw = Redis.from_url(store_settings.redis_url, decode_responses=True)
    try:
        # Two backends share one Redis, so the namespace is what keeps their
        # keys apart — and it has to be applied by the client, not by callers.
        assert await raw.exists(f"{client.key_prefix}scoped") == 1
        assert await raw.exists("scoped") == 0
    finally:
        await raw.aclose()


async def test_remember_loads_once_and_serves_the_rest_from_the_cache(
    cache: tuple[CacheService, PrefixedRedis],
) -> None:
    service, _ = cache
    calls = 0

    async def load() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": 42}

    first = await service.remember("report", CACHE_TTL_SECONDS, load)
    second = await service.remember("report", CACHE_TTL_SECONDS, load)

    assert first == second == {"value": 42}
    assert calls == 1


async def test_a_namespace_can_be_dropped_in_one_call(
    cache: tuple[CacheService, PrefixedRedis],
) -> None:
    service, _ = cache
    for index in range(5):
        await service.set(f"analytics:report:{index}", index, CACHE_TTL_SECONDS)
    await service.set("settings:default", "kept", CACHE_TTL_SECONDS)

    await service.invalidate_prefix("analytics:")

    assert await service.get("analytics:report:0") is None
    # Invalidating one namespace must not take the neighbours with it.
    assert await service.get("settings:default") == "kept"


@pytest.fixture
async def event_log(
    store_settings: Settings, mongodb_url: str
) -> AsyncIterator[tuple[EventStoreService, EventStore]]:
    settings = store_settings.model_copy(update={"mongodb_url": mongodb_url})
    store = EventStore(settings)
    await store.connect()
    if store.collection is None:
        await store.close()
        pytest.skip(f"MongoDB is not usable at MONGODB_URL: {mongodb_url.rsplit('@', 1)[-1]}")
    try:
        yield EventStoreService(store), store
    finally:
        await store.close()


def _event(entity_id: str, *, event_type: str = "contact.created") -> DomainEvent:
    return DomainEvent(
        event_type=event_type,
        entity_type="contact",
        entity_id=entity_id,
        actor_id=str(uuid.uuid4()),
        payload={"after": {"firstName": "Ada"}},
    )


async def test_an_appended_event_can_be_read_back(
    event_log: tuple[EventStoreService, EventStore],
) -> None:
    service, _ = event_log
    entity_id = str(uuid.uuid4())

    await service.append(_event(entity_id))

    history = await service.list_by_entity(
        EntityHistoryQuery(entity_type="contact", entity_id=entity_id, page=1, page_size=20)
    )
    assert history.total == 1
    record = history.items[0]
    assert record.event_type == "contact.created"
    assert record.payload == {"after": {"firstName": "Ada"}}


async def test_the_history_of_one_entity_is_newest_first(
    event_log: tuple[EventStoreService, EventStore],
) -> None:
    service, _ = event_log
    entity_id = str(uuid.uuid4())
    for event_type in ("contact.created", "contact.updated", "contact.deleted"):
        await service.append(_event(entity_id, event_type=event_type))

    history = await service.list_by_entity(
        EntityHistoryQuery(entity_type="contact", entity_id=entity_id, page=1, page_size=20)
    )

    assert [item.event_type for item in history.items] == [
        "contact.deleted",
        "contact.updated",
        "contact.created",
    ]


async def test_a_malformed_event_is_dropped_rather_than_raised(
    event_log: tuple[EventStoreService, EventStore],
) -> None:
    service, _ = event_log
    entity_id = str(uuid.uuid4())

    # Appending is fire-and-forget: a transaction that already committed must
    # never be reported as failed because its history could not be written.
    await service.append(DomainEvent(event_type="", entity_type="contact", entity_id=entity_id))

    history = await service.list_by_entity(
        EntityHistoryQuery(entity_type="contact", entity_id=entity_id, page=1, page_size=20)
    )
    assert history.total == 0


async def test_the_retention_index_is_created_with_its_window(
    event_log: tuple[EventStoreService, EventStore], store_settings: Settings
) -> None:
    _, store = event_log
    # The application declares a narrow port over the collection; reading its
    # index metadata is a driver capability the port deliberately omits.
    collection = cast("Any", store.collection)
    assert collection is not None

    indexes = await collection.index_information()

    assert collection.name == DOMAIN_EVENT_COLLECTION
    # Without this, an append-only collection grows until the disk is full.
    assert RETENTION_INDEX in indexes
    expected_seconds = store_settings.event_log_retention_days * 24 * 60 * 60
    assert indexes[RETENTION_INDEX]["expireAfterSeconds"] == expected_seconds


async def test_events_can_be_searched_by_type(
    event_log: tuple[EventStoreService, EventStore],
) -> None:
    service, _ = event_log
    event_type = f"probe.{uuid.uuid4().hex[:10]}"
    await service.append(_event(str(uuid.uuid4()), event_type=event_type))

    found = await service.search(EventSearchQuery(page=1, page_size=20, event_type=event_type))

    assert found.total == 1
    assert found.items[0].event_type == event_type
