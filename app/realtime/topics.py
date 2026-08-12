"""Topic vocabulary for the realtime channel.

Topics travel as plain strings, but every string that reaches the gateway is
parsed through :func:`parse_realtime_topic` first, so unknown or malformed names
never reach the subscription registry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal, cast, get_args

REALTIME_TOPIC_DEALS: Final = "deals"
REALTIME_TOPIC_ORDERS: Final = "orders"

RealtimeCollectionTopic = Literal["deals", "orders"]
RealtimeEntityType = Literal["deal", "order", "contact", "user"]

REALTIME_COLLECTION_TOPICS: Final[tuple[RealtimeCollectionTopic, ...]] = get_args(
    RealtimeCollectionTopic
)
REALTIME_ENTITY_TYPES: Final[tuple[RealtimeEntityType, ...]] = get_args(RealtimeEntityType)

#: Maximum accepted length of a topic string on the wire.
MAX_TOPIC_LENGTH: Final = 128

ENTITY_TOPIC_PREFIX: Final = "entity"
_ENTITY_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ENTITY_TOPIC_SEGMENTS: Final = 3

# Not every entity has a collection-wide stream: contacts and users are only
# broadcast per entity, so a subscriber cannot follow the whole table.
_ENTITY_TYPE_COLLECTION_TOPICS: Final[dict[RealtimeEntityType, RealtimeCollectionTopic]] = {
    "deal": "deals",
    "order": "orders",
}

_ENTITY_TYPE_RESOURCES: Final[dict[RealtimeEntityType, str]] = {
    "deal": "deals",
    "order": "orders",
    "contact": "contacts",
    "user": "users",
}


def is_realtime_entity_type(value: str) -> bool:
    """Type guard for the entity segment of a topic."""
    return value in REALTIME_ENTITY_TYPES


def is_realtime_collection_topic(value: str) -> bool:
    """Type guard for collection topics."""
    return value in REALTIME_COLLECTION_TOPICS


def deals_topic() -> str:
    """Builder for the ``deals`` collection topic."""
    return REALTIME_TOPIC_DEALS


def orders_topic() -> str:
    """Builder for the ``orders`` collection topic."""
    return REALTIME_TOPIC_ORDERS


def entity_topic(entity_type: RealtimeEntityType, entity_id: str) -> str:
    """Builder for a per-entity topic, e.g. ``entity:deal:clx123``."""
    return f"{ENTITY_TOPIC_PREFIX}:{entity_type}:{entity_id}"


def deal_topic(deal_id: str) -> str:
    """Convenience builder for a single deal stream."""
    return entity_topic("deal", deal_id)


def order_topic(order_id: str) -> str:
    """Convenience builder for a single order stream."""
    return entity_topic("order", order_id)


def collection_topic_for_entity(entity_type: str) -> str | None:
    """Collection topic an entity change also fans out to, when one exists."""
    if not is_realtime_entity_type(entity_type):
        return None
    return _ENTITY_TYPE_COLLECTION_TOPICS.get(cast(RealtimeEntityType, entity_type))


@dataclass(frozen=True, slots=True)
class ParsedRealtimeTopic:
    """Structured view of a validated topic string."""

    kind: Literal["collection", "entity"]
    topic: str
    entity_type: RealtimeEntityType | None = None
    entity_id: str | None = None


def _parse_entity_topic(value: str) -> ParsedRealtimeTopic | None:
    segments = value.split(":")
    if len(segments) != _ENTITY_TOPIC_SEGMENTS:
        return None

    prefix, entity_type, entity_id = segments
    if (
        prefix != ENTITY_TOPIC_PREFIX
        or not is_realtime_entity_type(entity_type)
        or _ENTITY_ID_PATTERN.match(entity_id) is None
    ):
        return None

    typed_entity = cast(RealtimeEntityType, entity_type)
    return ParsedRealtimeTopic(
        kind="entity",
        topic=entity_topic(typed_entity, entity_id),
        entity_type=typed_entity,
        entity_id=entity_id,
    )


def parse_realtime_topic(value: str) -> ParsedRealtimeTopic | None:
    """Parses a wire topic string.

    Returns ``None`` for anything outside the published vocabulary, which the
    gateway turns into an error frame instead of a subscription.
    """
    if not value or len(value) > MAX_TOPIC_LENGTH:
        return None

    if is_realtime_collection_topic(value):
        return ParsedRealtimeTopic(kind="collection", topic=value)

    return _parse_entity_topic(value)


def is_realtime_topic(value: str) -> bool:
    """Whether a client-supplied string names a known topic."""
    return parse_realtime_topic(value) is not None


@dataclass(frozen=True, slots=True)
class TopicPermissionRequirement:
    """Permission a subscriber must hold to follow a topic."""

    resource: str
    action: str


def topic_permission_requirement(topic: str) -> TopicPermissionRequirement | None:
    """Maps a topic onto the permission a subscriber needs.

    The gateway never calls this itself — it is exported so the composition root
    can implement ``can_subscribe`` on top of the RBAC service without
    duplicating the mapping, which is what keeps the realtime channel and the
    HTTP API enforcing exactly the same rules.
    """
    parsed = parse_realtime_topic(topic)
    if parsed is None:
        return None

    resource = (
        parsed.topic if parsed.entity_type is None else _ENTITY_TYPE_RESOURCES[parsed.entity_type]
    )

    return TopicPermissionRequirement(resource=resource, action="read")
