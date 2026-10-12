"""Process lifecycle.

The object graph is already built by the time this runs; what happens here is
connecting it, publishing it on ``app.state`` for the request dependencies, and
tearing it down in the reverse order on the way out.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.cache import close_redis_client
from app.container import Container
from app.core.logging import get_logger
from app.health.lifecycle import service_lifecycle

logger = get_logger("lifespan")


def build_lifespan(container: Container) -> Callable[[FastAPI], Any]:
    """Creates the lifespan handler bound to a concrete object graph."""
    settings = container.settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.database = container.database
        app.state.redis = container.redis
        app.state.cache = container.cache
        app.state.event_store = container.event_store
        app.state.events = container.events
        app.state.publisher = container.publisher
        app.state.realtime = container.gateway
        app.state.orders_stock = container.orders_stock
        app.state.resolve_organization_currency = container.resolve_organization_currency
        app.state.find_order_for_shipment = container.find_order_for_shipment
        # Both carry state that has to survive a request: the delivery client
        # holds the circuit breaker, the provider holds its connection pool.
        app.state.delivery_client = container.delivery_client
        app.state.ai_config = container.ai_config
        app.state.ai_provider = container.ai_provider
        app.state.call_provider_config = container.call_provider_config
        app.state.call_sync_batch_size = container.call_sync_batch_size

        # Never raises: a missing document store degrades history, not the API.
        await container.event_store.connect()

        service_lifecycle.mark_started()
        logger.info("service started", port=settings.port, environment=settings.app_env)

        try:
            yield
        finally:
            # The server already turned readiness 503, waited out the drain
            # delay and let in-flight requests finish (`app.core.server`); by
            # now nothing is being served. Marked again for the runs that stop
            # some other way — a test client leaving its context, say.
            service_lifecycle.begin_draining()

            await container.gateway.close()
            await container.publisher.drain()
            await container.event_store.close()
            await close_redis_client(container.redis)
            await container.database.dispose()

            service_lifecycle.mark_stopped()
            logger.info("service stopped")

    return lifespan
