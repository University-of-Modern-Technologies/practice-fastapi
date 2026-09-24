"""Publishing a domain event at the moment the change becomes real.

A service announces a change while its own transaction is still open: the
request session is committed by the dependency that opened it, after the
handler has returned. Publishing at announce time therefore reports a change
that a later failure can still undo, and a listener has no way to learn that it
never happened. The difference stays invisible while transactions succeed and
shows up exactly when one rolls back.

Deferring to the session's own ``after_commit`` keeps the announcement where
the service already writes it, and moves only its delivery.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.types import DomainEvent, DomainEventPublisher

__all__ = ["announcer", "publish_after_commit"]


def publish_after_commit(session: AsyncSession, publish: Callable[[], None]) -> None:
    """Defers an announcement until the session's transaction has committed.

    A session without the ORM event bus — a stand-in in a unit test — publishes
    immediately, which is the only thing it can honestly do.
    """
    sync_session = getattr(session, "sync_session", None)
    if sync_session is None:
        publish()
        return

    def _announce(_session: Any) -> None:
        publish()

    event.listen(sync_session, "after_commit", _announce, once=True)


def announcer(publisher: DomainEventPublisher, domain_event: DomainEvent) -> Callable[[], None]:
    """Wraps publication so a broken listener cannot fail a committed change."""

    def publish() -> None:
        with contextlib.suppress(Exception):
            publisher.publish(domain_event)

    return publish
