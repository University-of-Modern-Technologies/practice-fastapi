"""Registration and dispatch behaviour of the generic domain event subject."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.events import types as types_module
from app.events.types import DomainEvent, DomainEventSubject

EVENT = DomainEvent(
    event_type="deal.created",
    entity_type="deal",
    entity_id="d-1",
    actor_id="u-1",
    request_id="r-1",
)


class RecordingSubscriber:
    def __init__(self, name: str, order: list[str]) -> None:
        self.name = name
        self._order = order

    async def notify(self, event: DomainEvent) -> None:  # noqa: ARG002
        self._order.append(self.name)


async def test_subscribers_are_notified_in_registration_order() -> None:
    order: list[str] = []
    subject = DomainEventSubject()
    subject.subscribe(RecordingSubscriber("first", order))
    subject.subscribe(RecordingSubscriber("second", order))

    subject.publish(EVENT)
    await subject.drain()

    assert order == ["first", "second"]


async def test_a_subscriber_that_raises_does_not_stop_the_rest() -> None:
    order: list[str] = []

    class BrokenSubscriber:
        name = "broken"

        async def notify(self, event: DomainEvent) -> None:  # noqa: ARG002
            message = "subscriber is broken"
            raise RuntimeError(message)

    subject = DomainEventSubject()
    subject.subscribe(BrokenSubscriber())
    subject.subscribe(RecordingSubscriber("healthy", order))

    subject.publish(EVENT)
    await subject.drain()

    assert order == ["healthy"]


async def test_publish_never_raises_even_when_every_subscriber_fails() -> None:
    class BrokenSubscriber:
        name = "broken"

        async def notify(self, event: DomainEvent) -> None:  # noqa: ARG002
            message = "subscriber is broken"
            raise RuntimeError(message)

    subject = DomainEventSubject()
    subject.subscribe(BrokenSubscriber())

    subject.publish(EVENT)  # must not raise
    await subject.drain()


async def test_unsubscribe_stops_further_notifications() -> None:
    order: list[str] = []
    subject = DomainEventSubject()
    unsubscribe = subject.subscribe(RecordingSubscriber("sub", order))

    subject.publish(EVENT)
    await subject.drain()
    unsubscribe()
    subject.publish(EVENT)
    await subject.drain()

    assert order == ["sub"]


def test_publish_outside_an_event_loop_is_a_no_op() -> None:
    """Offline tooling and scripts may publish with no loop running."""
    order: list[str] = []
    subject = DomainEventSubject()
    subject.subscribe(RecordingSubscriber("sub", order))

    subject.publish(EVENT)  # must not raise despite no running loop

    assert order == []


async def test_drain_awaits_all_pending_deliveries() -> None:
    order: list[str] = []

    class SlowSubscriber:
        name = "slow"

        async def notify(self, event: DomainEvent) -> None:  # noqa: ARG002
            await asyncio.sleep(0.05)
            order.append("slow")

    subject = DomainEventSubject()
    subject.subscribe(SlowSubscriber())

    subject.publish(EVENT)
    await subject.drain()

    assert order == ["slow"]


class RecordingLogger:
    def __init__(self) -> None:
        self.errors: list[tuple[str, dict[str, Any]]] = []

    def error(self, message: str, **fields: Any) -> None:
        self.errors.append((message, fields))


async def test_a_failing_subscriber_is_logged_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A suppressed failure left nothing behind: the log is the only witness."""
    logger = RecordingLogger()
    monkeypatch.setattr(types_module, "_logger", logger)

    class BrokenSubscriber:
        name = "broken"

        async def notify(self, event: DomainEvent) -> None:  # noqa: ARG002
            message = "subscriber is broken"
            raise RuntimeError(message)

    subject = DomainEventSubject()
    subject.subscribe(BrokenSubscriber())

    subject.publish(EVENT)
    await subject.drain()

    assert len(logger.errors) == 1
    message, fields = logger.errors[0]
    assert message == "Domain event subscriber failed"
    assert fields["subscriber"] == "broken"
    assert "subscriber is broken" in fields["err"]


async def test_a_stalled_subscriber_does_not_hold_up_the_next_one() -> None:
    """A WebSocket peer that stopped reading must not delay the event log."""
    stalled = asyncio.Event()
    order: list[str] = []

    class StalledSubscriber:
        name = "realtime"

        async def notify(self, event: DomainEvent) -> None:  # noqa: ARG002
            await stalled.wait()
            order.append("realtime")

    subject = DomainEventSubject()
    subject.subscribe(StalledSubscriber())
    subject.subscribe(RecordingSubscriber("event-log", order))

    subject.publish(EVENT)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert order == ["event-log"]

    stalled.set()
    await subject.drain()
    assert order == ["event-log", "realtime"]
