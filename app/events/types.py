"""Event log vocabulary and ports.

PostgreSQL stays the source of truth for domain data, so an entry in this log is
a denormalised snapshot of something that already happened — never a record the
business logic reads back inside a transaction.

The storage side is expressed as narrow protocols rather than driver types. That
is what lets the service run in unit tests against a plain object, and it keeps
the choice of driver from leaking into thirteen domain modules.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

#: Anything that survives a round trip through the document store.
EventJsonValue = (
    str | int | float | bool | None | list["EventJsonValue"] | dict[str, "EventJsonValue"]
)

#: Query document handed to the driver.
EventFilter = dict[str, Any]


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """A committed domain change, on its way out of the transaction.

    Publishing happens *after* the database transaction commits and is
    deliberately fire-and-forget: the event log and the realtime channel are
    secondary consumers, so neither may delay nor roll back the operation that
    produced them.
    """

    event_type: str
    entity_type: str
    entity_id: str
    actor_id: str | None = None
    request_id: str | None = None
    payload: Any = None
    #: Left unset by callers; the store stamps the moment of the append.
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DomainEventDto:
    """A stored event as it is handed back to a reader."""

    id: str
    event_type: str
    entity_type: str
    entity_id: str
    actor_id: str | None
    request_id: str | None
    payload: EventJsonValue
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class EntityHistoryQuery:
    entity_type: str
    entity_id: str
    page: int
    page_size: int


@dataclass(frozen=True, slots=True)
class EventSearchQuery:
    page: int
    page_size: int
    event_type: str | None = None
    actor_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class EventListResult:
    """The same pagination envelope every collection endpoint returns."""

    items: list[DomainEventDto]
    page: int
    page_size: int
    total: int


class DomainEventPublisher(Protocol):
    """Outbound notification of a committed domain change.

    Synchronous and returning nothing: a publisher may never make a domain
    operation wait on the delivery of its own side effects.
    """

    def publish(self, event: DomainEvent) -> None: ...


class NoopPublisher:
    """Default for callers constructed without the fan-out infrastructure."""

    def publish(self, event: DomainEvent) -> None:
        """Intentionally empty: unit tests and offline tooling need no fan-out."""


class DomainEventSubscriber(Protocol):
    """A secondary consumer registered against a :class:`DomainEventSubject`.

    ``notify`` may raise or its awaitable may reject; the subject contains
    either case, so one subscriber's failure can never stop the rest from
    being notified.
    """

    @property
    def name(self) -> str:
        """Identifies the subscriber in diagnostics."""
        ...

    async def notify(self, event: DomainEvent) -> None: ...


@dataclass(slots=True)
class DomainEventSubject:
    """Fans a published event out to whatever subscribers are registered.

    Subscribers are notified in registration order, sequentially rather than
    concurrently: some deployments rely on that order (a slow secondary
    consumer must not delay a faster one that was registered ahead of it), so
    dispatch stays a simple loop instead of ``gather``. Each subscriber is
    wrapped in its own ``suppress`` so a failure never stops the rest, and
    ``publish`` itself never raises: the operation that produced the event has
    already committed and must be reported as successful regardless of what
    its secondary consumers do.
    """

    _subscribers: list[DomainEventSubscriber] = field(default_factory=list)
    # Tasks are held until they finish; without a strong reference the event
    # loop is free to garbage-collect a task mid-flight.
    _pending: set[asyncio.Task[None]] = field(default_factory=set)

    def subscribe(self, subscriber: DomainEventSubscriber) -> Callable[[], None]:
        """Registers a subscriber and returns the matching unsubscribe."""
        self._subscribers.append(subscriber)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._subscribers.remove(subscriber)

        return unsubscribe

    def publish(self, event: DomainEvent) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Published from outside an event loop (a script, a test); the
            # secondary consumers are optional, so this is not an error.
            return

        task = loop.create_task(self._deliver(event))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _deliver(self, event: DomainEvent) -> None:
        for subscriber in list(self._subscribers):
            with contextlib.suppress(Exception):
                await subscriber.notify(event)

    async def drain(self) -> None:
        """Waits for in-flight deliveries so shutdown does not cut them short."""
        if not self._pending:
            return
        await asyncio.gather(*list(self._pending), return_exceptions=True)


class DomainEventCursor(Protocol):
    """The cursor operations the read path uses, and nothing else."""

    def sort(self, key_or_list: Sequence[tuple[str, int]]) -> DomainEventCursor: ...

    def skip(self, skip: int) -> DomainEventCursor: ...

    def limit(self, limit: int) -> DomainEventCursor: ...

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]: ...


class DomainEventCollection(Protocol):
    """Minimal port over the events collection."""

    async def insert_one(self, document: Mapping[str, Any]) -> Any: ...

    def find(self, spec: Mapping[str, Any]) -> DomainEventCursor: ...

    async def count_documents(self, spec: Mapping[str, Any]) -> int: ...

    async def create_index(self, keys: Sequence[tuple[str, int]], **kwargs: Any) -> str: ...

    async def drop_index(self, index_or_name: str) -> None: ...


class DomainEventSource(Protocol):
    """Supplier of the collection, or ``None`` while the store is unreachable.

    Indirection rather than a plain collection reference, because the service is
    constructed at boot while the connection is established in the background.
    """

    @property
    def collection(self) -> DomainEventCollection | None: ...
