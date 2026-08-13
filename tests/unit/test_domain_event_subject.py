"""Registration and dispatch behaviour of the generic domain event subject."""

from __future__ import annotations

import asyncio

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
