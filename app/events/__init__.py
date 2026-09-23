"""Append-only domain event log on MongoDB."""

from __future__ import annotations

from app.events.connection import EventStore, create_event_store_readiness_check
from app.events.dispatch import announcer, publish_after_commit
from app.events.model import DOMAIN_EVENT_COLLECTION, ensure_indexes
from app.events.sanitize import is_sensitive_event_field, sanitize_event_payload
from app.events.service import EventStoreService, EventStoreUnavailableError
from app.events.types import (
    DomainEvent,
    DomainEventCollection,
    DomainEventDto,
    DomainEventPublisher,
    DomainEventSource,
    DomainEventSubject,
    DomainEventSubscriber,
    EntityHistoryQuery,
    EventListResult,
    EventSearchQuery,
    NoopPublisher,
)

__all__ = [
    "DOMAIN_EVENT_COLLECTION",
    "DomainEvent",
    "DomainEventCollection",
    "DomainEventDto",
    "DomainEventPublisher",
    "DomainEventSource",
    "DomainEventSubject",
    "DomainEventSubscriber",
    "EntityHistoryQuery",
    "EventListResult",
    "EventSearchQuery",
    "EventStore",
    "EventStoreService",
    "EventStoreUnavailableError",
    "NoopPublisher",
    "announcer",
    "create_event_store_readiness_check",
    "ensure_indexes",
    "is_sensitive_event_field",
    "publish_after_commit",
    "sanitize_event_payload",
]
