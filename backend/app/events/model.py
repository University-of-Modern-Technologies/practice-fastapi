"""Collection layout for the event log.

There is no schema to declare — the store is schemaless — so what is described
here is the part that actually matters: the indexes. Three of them serve the
queries the log supports, and the fourth one is what keeps an append-only
collection from growing without bound.

Field names are camelCase, matching the documents already in the collection: a
shared collection with two spellings of the same field is two schemas, and every
query would have to know which one it is reading.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.events.types import DomainEventCollection

logger = get_logger("events")

DOMAIN_EVENT_COLLECTION = "domain_events"
DEFAULT_EVENT_DATABASE = "practice_events"

SECONDS_PER_DAY = 24 * 60 * 60

EVENT_TYPE_INDEX = "event_type_idx"
ENTITY_HISTORY_INDEX = "entity_history_idx"
ACTOR_HISTORY_INDEX = "actor_history_idx"
RETENTION_INDEX = "occurred_at_ttl_idx"


#: The server refuses to reuse an index name for a different definition. Both
#: codes mean the same thing here: an index of this name exists but is not the
#: one being asked for.
_INDEX_CONFLICT_CODES = frozenset({85, 86})


def _is_index_conflict(error: Exception) -> bool:
    return getattr(error, "code", None) in _INDEX_CONFLICT_CODES


async def _ensure_index(
    collection: DomainEventCollection,
    keys: list[tuple[str, int]],
    name: str,
    **options: Any,
) -> None:
    """Creates one index, replacing an older definition of the same name.

    Without the replacement this function is only idempotent while the
    definitions never change: the first time a key or an expiry is adjusted the
    server rejects the request, and — because the indexes are created in one
    sequence — every index after the rejected one is silently skipped too.
    """
    try:
        await collection.create_index(keys, name=name, **options)
    except Exception as error:
        if not _is_index_conflict(error):
            raise
        logger.info("Replacing an outdated event log index", index=name)
        await collection.drop_index(name)
        await collection.create_index(keys, name=name, **options)


async def ensure_indexes(collection: DomainEventCollection, retention_days: int) -> None:
    """Creates the indexes the log depends on. Idempotent."""
    # Search filtered by event type alone.
    await _ensure_index(collection, [("eventType", 1)], EVENT_TYPE_INDEX)
    # Entity history: newest first for one entity.
    await _ensure_index(
        collection,
        [("entityType", 1), ("entityId", 1), ("occurredAt", -1)],
        ENTITY_HISTORY_INDEX,
    )
    # Actor-scoped search and analytics.
    await _ensure_index(
        collection,
        [("actorId", 1), ("occurredAt", -1)],
        ACTOR_HISTORY_INDEX,
    )
    # Retention: the server prunes an event once the window elapses, so nothing
    # in the application has to own a cleanup job.
    await _ensure_index(
        collection,
        [("occurredAt", 1)],
        RETENTION_INDEX,
        expireAfterSeconds=retention_days * SECONDS_PER_DAY,
    )
