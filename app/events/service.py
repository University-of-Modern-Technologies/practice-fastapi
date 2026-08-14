"""Append-only domain event log.

Two rules shape this module. Appending never raises, because a business
transaction that already committed in PostgreSQL must not be reported as failed
just because its history could not be written. Reading, by contrast, is an
ordinary query and reports its failures normally.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from app.core.errors import AppError
from app.core.logging import get_logger
from app.events.sanitize import sanitize_event_payload
from app.events.types import (
    DomainEvent,
    DomainEventCollection,
    DomainEventDto,
    DomainEventSource,
    EntityHistoryQuery,
    EventFilter,
    EventListResult,
    EventSearchQuery,
)

logger = get_logger("events")

_MAX_TYPE_LENGTH = 128
_MAX_NAME_LENGTH = 64

_EventType = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=_MAX_TYPE_LENGTH)
]
_Identifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=_MAX_TYPE_LENGTH)
]
_ShortName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=_MAX_NAME_LENGTH)
]


class _ValidatedEvent(BaseModel):
    """Guards the append path: a malformed event is dropped, never persisted."""

    model_config = ConfigDict(extra="forbid")

    event_type: _EventType
    entity_type: _ShortName
    entity_id: _Identifier
    actor_id: _Identifier | None = None
    request_id: _Identifier | None = None
    payload: Any = None
    occurred_at: datetime | None = None


class EventStoreUnavailableError(AppError):
    """The log was queried while the document store was unreachable."""

    def __init__(self) -> None:
        super().__init__("Event history is temporarily unavailable", 503, "EVENT_STORE_UNAVAILABLE")


def _to_dto(record: dict[str, Any]) -> DomainEventDto:
    occurred_at = record.get("occurredAt")
    if not isinstance(occurred_at, datetime):
        occurred_at = datetime.now(UTC)
    return DomainEventDto(
        id=str(record.get("_id", "")),
        event_type=str(record.get("eventType", "")),
        entity_type=str(record.get("entityType", "")),
        entity_id=str(record.get("entityId", "")),
        actor_id=record.get("actorId"),
        request_id=record.get("requestId"),
        payload=record.get("payload"),
        # Timestamps come back without a zone; they were written as UTC, and
        # every consumer of this DTO renders UTC.
        occurred_at=occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC),
    )


def _occurred_at_filter(date_from: datetime | None, date_to: datetime | None) -> EventFilter:
    window: EventFilter = {}
    if date_from is not None:
        window["$gte"] = date_from
    if date_to is not None:
        window["$lte"] = date_to
    return {"occurredAt": window} if window else {}


class EventStoreService:
    """Writes and reads the event log."""

    def __init__(self, source: DomainEventSource) -> None:
        self._source = source

    def _require_collection(self) -> DomainEventCollection:
        collection = self._source.collection
        if collection is None:
            raise EventStoreUnavailableError
        return collection

    async def append(self, event: DomainEvent) -> None:
        """Fire-and-forget append. Never raises."""
        try:
            validated = _ValidatedEvent(
                event_type=event.event_type,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                actor_id=event.actor_id,
                request_id=event.request_id,
                payload=event.payload,
                occurred_at=event.occurred_at,
            )
        except ValidationError as error:
            logger.warning(
                "Dropped a malformed domain event",
                eventType=event.event_type,
                issues=error.error_count(),
            )
            return

        try:
            collection = self._source.collection
            if collection is None:
                logger.warning(
                    "Dropped a domain event: the store is unavailable",
                    eventType=validated.event_type,
                )
                return

            await collection.insert_one(
                {
                    "eventType": validated.event_type,
                    "entityType": validated.entity_type,
                    "entityId": validated.entity_id,
                    "actorId": validated.actor_id,
                    "requestId": validated.request_id,
                    "payload": sanitize_event_payload(validated.payload),
                    "occurredAt": validated.occurred_at or datetime.now(UTC),
                }
            )
        except Exception as error:
            logger.error(
                "Failed to append a domain event",
                eventType=validated.event_type,
                err=repr(error),
            )

    async def _paginate(self, spec: EventFilter, page: int, page_size: int) -> EventListResult:
        collection = self._require_collection()
        records = await (
            collection.find(spec)
            # `_id` breaks ties so that two events stamped in the same
            # millisecond keep a stable order across pages.
            .sort([("occurredAt", -1), ("_id", -1)])
            .skip((page - 1) * page_size)
            .limit(page_size)
            .to_list(page_size)
        )
        total = await collection.count_documents(spec)
        return EventListResult(
            items=[_to_dto(record) for record in records],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def list_by_entity(self, query: EntityHistoryQuery) -> EventListResult:
        return await self._paginate(
            {"entityType": query.entity_type, "entityId": query.entity_id},
            query.page,
            query.page_size,
        )

    async def search(self, query: EventSearchQuery) -> EventListResult:
        spec: EventFilter = {}
        if query.event_type:
            spec["eventType"] = query.event_type
        if query.actor_id:
            spec["actorId"] = query.actor_id
        spec.update(_occurred_at_filter(query.date_from, query.date_to))
        return await self._paginate(spec, query.page, query.page_size)
