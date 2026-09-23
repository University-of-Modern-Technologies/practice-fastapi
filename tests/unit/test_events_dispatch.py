"""What a listener is allowed to hear, and when.

The rule under test is the one that only shows itself when a transaction fails:
a change that rolled back must leave no trace outside the process. Publishing at
announce time satisfies every green-path assertion and still breaks this, which
is why the ordering is asserted here rather than left to the services.

No database is involved. The deferral rides on the session's own ``after_commit``
event, and the ORM emits that from the synchronous session underneath — so an
``AsyncSession`` that never opened a connection is enough to observe it.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.dispatch import announcer, publish_after_commit
from app.events.types import DomainEvent


class RecordingPublisher:
    """Stands in for the fan-out and remembers what reached it."""

    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.published.append(event)


class BrokenPublisher:
    """A listener that fails, to prove a committed write still succeeds."""

    def publish(self, event: DomainEvent) -> None:  # noqa: ARG002
        raise RuntimeError("event stream unreachable")


def make_event(event_type: str = "product.created") -> DomainEvent:
    return DomainEvent(
        event_type=event_type,
        entity_type="product",
        entity_id="7c9e6679-7425-40de-944b-e07fc1f90ae7",
        actor_id="1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
        payload={},
    )


@pytest.fixture
def session() -> AsyncSession:
    """A session with a real ORM event bus and no connection behind it."""
    return AsyncSession()


def commit(session: AsyncSession) -> None:
    """Fires the lifecycle event a real commit fires, without a connection."""
    sync = session.sync_session
    sync.dispatch.after_commit(sync)


def rollback(session: AsyncSession) -> None:
    """The same for the path where the transaction is undone."""
    sync = session.sync_session
    sync.dispatch.after_rollback(sync)


def test_holds_the_event_until_the_session_commits(session: AsyncSession) -> None:
    publisher = RecordingPublisher()

    publish_after_commit(session, announcer(publisher, make_event()))
    assert publisher.published == [], "announced before the commit"

    commit(session)
    assert [event.event_type for event in publisher.published] == ["product.created"]


def test_stays_silent_when_the_transaction_rolls_back(session: AsyncSession) -> None:
    publisher = RecordingPublisher()

    publish_after_commit(session, announcer(publisher, make_event()))
    rollback(session)

    assert publisher.published == [], "announced a change that never happened"


def test_announces_once_even_if_the_session_commits_again(session: AsyncSession) -> None:
    publisher = RecordingPublisher()

    publish_after_commit(session, announcer(publisher, make_event()))
    commit(session)
    commit(session)

    assert len(publisher.published) == 1


def test_keeps_a_committed_write_successful_when_a_listener_fails(session: AsyncSession) -> None:
    publish_after_commit(session, announcer(BrokenPublisher(), make_event()))

    commit(session)


def test_publishes_immediately_without_an_orm_event_bus() -> None:
    """A stand-in session cannot defer, so it must not swallow the event."""
    publisher = RecordingPublisher()
    stand_in: Any = object()

    publish_after_commit(stand_in, announcer(publisher, make_event()))

    assert len(publisher.published) == 1
