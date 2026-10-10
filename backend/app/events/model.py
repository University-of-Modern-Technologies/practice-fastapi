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

# The sibling backend creates the same indexes under the same names, so an index
# listing reads identically whichever one built the collection.
EVENT_TYPE_INDEX = "event_type_idx"
ENTITY_HISTORY_INDEX = "entity_history_idx"
ACTOR_HISTORY_INDEX = "actor_history_idx"
RETENTION_INDEX = "occurred_at_ttl_idx"


#: What the server answers when an index cannot be created as asked because one
#: already exists that is almost the same: the same name for other keys or
#: options (86 / 85), or the same keys under another name (85).
_INDEX_CONFLICT_CODES = frozenset({85, 86})

_PRIMARY_KEY_INDEX = "_id_"


def _is_index_conflict(error: Exception) -> bool:
    return getattr(error, "code", None) in _INDEX_CONFLICT_CODES


def _same_keys(stored: Any, keys: list[tuple[str, int]]) -> bool:
    return [(str(field), int(direction)) for field, direction in stored or ()] == keys


async def _ensure_index(
    collection: DomainEventCollection,
    keys: list[tuple[str, int]],
    name: str,
    **options: Any,
) -> None:
    """Creates one index, replacing whatever stands in its way.

    That is an older definition under the same name, or the same keys under
    another name. Without the replacement this function is only idempotent
    while the definitions never change: the first time a key or an expiry is
    adjusted the server rejects the request, and — because the indexes are
    created in one sequence — every index after the rejected one is silently
    skipped too.
    """
    try:
        await collection.create_index(keys, name=name, **options)
    except Exception as error:
        if not _is_index_conflict(error):
            raise
        existing = await collection.index_information()
        obstacles = [
            existing_name
            for existing_name, description in existing.items()
            if existing_name != _PRIMARY_KEY_INDEX
            and (existing_name == name or _same_keys(description.get("key"), keys))
        ]
        logger.info("Replacing an outdated event log index", index=name, replaced=obstacles)
        for obstacle in obstacles:
            await collection.drop_index(obstacle)
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
