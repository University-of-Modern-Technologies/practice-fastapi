"""Access to the event publisher from a request handler.

Domain services announce what changed; they do not know, and must not care,
whether anybody is listening. The publisher is therefore resolved from the
application state and degrades to a no-op when the process was assembled
without one — which is exactly the case in unit tests.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.events.types import DomainEventPublisher, NoopPublisher

_NOOP = NoopPublisher()


def get_publisher(request: Request) -> DomainEventPublisher:
    publisher = getattr(request.app.state, "publisher", None)
    if publisher is None:
        return _NOOP
    published: DomainEventPublisher = publisher
    return published


PublisherDep = Annotated[DomainEventPublisher, Depends(get_publisher)]
