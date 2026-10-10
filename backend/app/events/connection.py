"""Event store connectivity.

A store that is down at startup must not abort the boot: the handshake failure
path here logs and returns instead of propagating. The driver re-establishes the
connection on its own, and a background task keeps asking until the store
answers, so the indexes are created then rather than on the next boot. The
instance reports itself unready until the store answers — see the readiness
check below — and ready as soon as it does.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
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

#: Pause between handshakes while the store is unreachable. The sibling backend
#: waits as long (`EVENT_STORE_RETRY_DELAY_MS`).
RETRY_DELAY_SECONDS = 5.0

EVENT_STORE_READINESS_CHECK_NAME = "event-store"

ClientFactory = Callable[..., Any]


class EventStore:
    """Owns the client and exposes the events collection."""

    def __init__(
        self,
        settings: Settings,
        *,
        retry_delay_seconds: float = RETRY_DELAY_SECONDS,
        client_factory: ClientFactory = AsyncMongoClient,
    ) -> None:
        self._settings = settings
        self._retry_delay_seconds = retry_delay_seconds
        self._client_factory = client_factory
        self._client: AsyncMongoClient[dict[str, Any]] | None = None
        self._collection: DomainEventCollection | None = None
        self._retry: asyncio.Task[None] | None = None

    @property
    def collection(self) -> DomainEventCollection | None:
        return self._collection

    async def connect(self) -> None:
        """Opens the client and creates the indexes. Never raises."""
        if self._client is not None:
            return

        client: AsyncMongoClient[dict[str, Any]] = self._client_factory(
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

        if not await self._initialise():
            # The collection reference is kept: the driver reconnects on its
            # own, so appends start succeeding again without a restart. What
            # waits for the store is the index creation.
            self._retry = asyncio.create_task(
                self._retry_until_reachable(), name="event-store-retry"
            )

    async def _initialise(self) -> bool:
        """Pings the store and, once it answers, creates the indexes.

        Returns whether the store answered. An index failure is logged and not
        retried: appends work without the indexes, and a store that answers
        but refuses them will not change its mind in five seconds.
        """
        client, collection = self._client, self._collection
        if client is None or collection is None:
            return True
        try:
            await client.admin.command("ping")
        except Exception as error:
            logger.error(
                "Event store is unavailable; retrying in the background",
                err=repr(error),
                retryInSeconds=self._retry_delay_seconds,
            )
            return False

        try:
            await ensure_indexes(collection, self._settings.event_log_retention_days)
        except Exception as error:
            logger.error("Failed to create the event log indexes", err=repr(error))

        logger.info("Event store connected")
        return True

    async def _retry_until_reachable(self) -> None:
        while True:
            await asyncio.sleep(self._retry_delay_seconds)
            if await self._initialise():
                return

    async def ping(self) -> None:
        """Readiness probe: raises when the store cannot be reached."""
        if self._client is None:
            message = "Event store is not initialised"
            raise RuntimeError(message)
        await self._client.admin.command("ping")

    async def close(self) -> None:
        if self._retry is not None:
            retry, self._retry = self._retry, None
            retry.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await retry
        if self._client is None:
            return
        client, self._client, self._collection = self._client, None, None
        try:
            await client.close()
        except Exception as error:  # shutdown must not fail on a dead dependency
            logger.warning("Failed to close the event store client", err=repr(error))


def create_event_store_readiness_check(store: EventStore) -> ReadinessCheck:
    """Probe for ``/api/health/ready``.

    Critical: an instance that cannot reach the store loses the event log
    silently, so it is taken out of rotation rather than left accepting traffic
    it can only half-record.
    """
    return ReadinessCheck(
        name=EVENT_STORE_READINESS_CHECK_NAME,
        check=store.ping,
    )
