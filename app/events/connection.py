"""Event store connectivity.

A store that is down at startup must not abort the boot: the handshake failure
path here logs and returns instead of propagating, and the driver is left to
re-establish the connection in the background. The instance still reports itself
unready until the store answers again — see the readiness check below.
"""

from __future__ import annotations

from typing import Any, cast

from pymongo import AsyncMongoClient

from app.core.logging import get_logger
from app.core.settings import Settings
from app.events.model import (
    DEFAULT_EVENT_DATABASE,
    DOMAIN_EVENT_COLLECTION,
    ensure_indexes,
)
from app.events.types import DomainEventCollection
from app.health.readiness import ReadinessCheck

logger = get_logger("events")

SERVER_SELECTION_TIMEOUT_MS = 5_000
CONNECT_TIMEOUT_MS = 10_000
SOCKET_TIMEOUT_MS = 45_000
MAX_POOL_SIZE = 10

EVENT_STORE_READINESS_CHECK_NAME = "event-store"


class EventStore:
    """Owns the client and exposes the events collection."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncMongoClient[dict[str, Any]] | None = None
        self._collection: DomainEventCollection | None = None

    @property
    def collection(self) -> DomainEventCollection | None:
        return self._collection

    async def connect(self) -> None:
        """Opens the client and creates the indexes. Never raises."""
        if self._client is not None:
            return

        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
            self._settings.mongodb_url,
            serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
            connectTimeoutMS=CONNECT_TIMEOUT_MS,
            socketTimeoutMS=SOCKET_TIMEOUT_MS,
            maxPoolSize=MAX_POOL_SIZE,
        )
        self._client = client
        database = client.get_default_database(default=DEFAULT_EVENT_DATABASE)
        # The collection satisfies the port structurally; the cast states that
        # once, here, so no other module has to know the driver's types.
        self._collection = cast(DomainEventCollection, database[DOMAIN_EVENT_COLLECTION])

        try:
            await client.admin.command("ping")
            await ensure_indexes(self._collection, self._settings.event_log_retention_days)
        except Exception as error:
            # The collection reference is kept: the driver reconnects on its own,
            # so appends start succeeding again without a restart. Only the
            # indexes are missed, and they are created on the next boot.
            logger.error("Event store is unavailable at startup", err=repr(error))
            return

        logger.info("Event store connected")

    async def ping(self) -> None:
        """Readiness probe: raises when the store cannot be reached."""
        if self._client is None:
            message = "Event store is not initialised"
            raise RuntimeError(message)
        await self._client.admin.command("ping")

    async def close(self) -> None:
        if self._client is None:
            return
        client, self._client, self._collection = self._client, None, None
        try:
            await client.close()
        except Exception as error:  # shutdown must not fail on a dead dependency
            logger.warning("Failed to close the event store client", err=repr(error))


def create_event_store_readiness_check(store: EventStore) -> ReadinessCheck:
    """Probe for ``/health/ready``.

    Critical: an instance that cannot reach the store loses the event log
    silently, so it is taken out of rotation rather than left accepting traffic
    it can only half-record.
    """
    return ReadinessCheck(
        name=EVENT_STORE_READINESS_CHECK_NAME,
        check=store.ping,
    )
