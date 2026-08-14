"""Fan-out of a committed change to the two secondary consumers."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from app.container import FanOutPublisher
from app.events.types import DomainEvent
from app.modules.contacts.service import ContactsService
from app.modules.settings.service import SettingsService

EVENT = DomainEvent(
    event_type="deal.created",
    entity_type="deal",
    entity_id="d-1",
    actor_id="u-1",
    request_id="r-1",
)


class SlowEventStore:
    """A degraded document store: appending works, but takes a while."""

    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.appended: list[DomainEvent] = []

    async def append(self, event: DomainEvent) -> None:
        await asyncio.sleep(0.05)
        self.appended.append(event)
        self._order.append("events")


class RecordingGateway:
    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.published: list[tuple[str, Any]] = []

    async def publish(self, topic: str, event: Any) -> None:
        self.published.append((topic, event))
        self._order.append("realtime")


async def test_realtime_is_served_before_the_event_log() -> None:
    """A slow document store must not hold up connected clients."""
    order: list[str] = []
    events = SlowEventStore(order)
    gateway = RecordingGateway(order)
    publisher = FanOutPublisher(events, gateway)  # type: ignore[arg-type]

    publisher.publish(EVENT)
    await publisher.drain()

    assert order[0] == "realtime"
    assert order[-1] == "events"
    assert events.appended == [EVENT]


async def test_a_failing_event_log_still_leaves_the_realtime_fan_out_done() -> None:
    class BrokenEventStore:
        async def append(self, event: DomainEvent) -> None:  # noqa: ARG002
            message = "store is unreachable"
            raise ConnectionError(message)

    gateway = RecordingGateway([])
    publisher = FanOutPublisher(BrokenEventStore(), gateway)  # type: ignore[arg-type]

    publisher.publish(EVENT)
    await publisher.drain()

    assert [topic for topic, _payload in gateway.published] == ["deals", "entity:deal:d-1"]


async def test_a_failing_realtime_gateway_still_leaves_the_event_log_written() -> None:
    class BrokenGateway:
        async def publish(self, topic: str, event: Any) -> None:  # noqa: ARG002
            message = "gateway is unreachable"
            raise ConnectionError(message)

    events = SlowEventStore([])
    publisher = FanOutPublisher(events, BrokenGateway())  # type: ignore[arg-type]

    publisher.publish(EVENT)
    await publisher.drain()

    assert events.appended == [EVENT]


async def test_the_realtime_payload_uses_the_wire_field_names() -> None:
    gateway = RecordingGateway([])
    publisher = FanOutPublisher(SlowEventStore([]), gateway)  # type: ignore[arg-type]

    publisher.publish(EVENT)
    await publisher.drain()

    _topic, payload = gateway.published[0]
    assert payload["eventType"] == "deal.created"
    assert payload["entityId"] == "d-1"


def test_contacts_and_settings_stay_out_of_the_event_log() -> None:
    """Neither module can reach a publisher, so neither can widen the vocabulary.

    A contact or a setting change is recorded in the audit trail, not in the
    domain event log — the sibling deployment draws the line in the same place.
    Taking the publisher out of the constructors is what enforces it, so the
    signatures are the thing worth guarding.
    """
    for service in (ContactsService, SettingsService):
        parameters = set(inspect.signature(service.__init__).parameters)
        assert not parameters & {"events", "publisher"}


class HalfBrokenGateway:
    """One stream is down, the other is healthy."""

    def __init__(self, broken_topic: str) -> None:
        self._broken_topic = broken_topic
        self.published: list[str] = []

    async def publish(self, topic: str, _event: Any) -> None:
        self.published.append(topic)
        if topic == self._broken_topic:
            message = f"{topic} is unreachable"
            raise ConnectionError(message)


async def test_a_broken_collection_stream_still_reaches_the_record_stream() -> None:
    """A client watching one deal must not go silent because the list feed broke."""
    gateway = HalfBrokenGateway("deals")
    publisher = FanOutPublisher(SlowEventStore([]), gateway)  # type: ignore[arg-type]

    publisher.publish(EVENT)
    await publisher.drain()

    assert gateway.published == ["deals", "entity:deal:d-1"]


async def test_a_broken_record_stream_still_reaches_the_collection_stream() -> None:
    gateway = HalfBrokenGateway("entity:deal:d-1")
    publisher = FanOutPublisher(SlowEventStore([]), gateway)  # type: ignore[arg-type]

    publisher.publish(EVENT)
    await publisher.drain()

    assert gateway.published == ["deals", "entity:deal:d-1"]


async def test_a_stream_failure_does_not_cost_the_event_log() -> None:
    events = SlowEventStore([])
    publisher = FanOutPublisher(events, HalfBrokenGateway("deals"))  # type: ignore[arg-type]

    publisher.publish(EVENT)
    await publisher.drain()

    assert events.appended == [EVENT]
