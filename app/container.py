"""Composition root.

Every long-lived object is built here, once, and handed to whoever needs it.
Nothing in this module is imported by the modules themselves: dependencies point
inwards, so a domain module never learns that a cache, an event log or a
WebSocket gateway exists.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, cast

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import (
    CacheService,
    NoopCacheService,
    PrefixedRedis,
    create_cache_readiness_check,
    create_redis_client,
)
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models.warehouse import Warehouse
from app.db.session import Database
from app.events import (
    EventStore,
    EventStoreService,
    create_event_store_readiness_check,
)
from app.events.types import DomainEvent, DomainEventSubject
from app.health.database import create_database_readiness_check
from app.health.readiness import ReadinessCheck
from app.infra_profile import create_infra_stack
from app.modules.ai import AiConfig, create_ai_router
from app.modules.ai.provider import AiProvider
from app.modules.analytics import create_analytics_router
from app.modules.audit import create_audit_router
from app.modules.auth import AuthService, auth_config_from_settings, create_auth_router
from app.modules.calls import CallProviderConfig, create_calls_router
from app.modules.contacts import create_contacts_router
from app.modules.deals import create_deals_router
from app.modules.helpdesk import create_helpdesk_router
from app.modules.integrations import DeliveryClient, create_integrations_router
from app.modules.orders import create_orders_router
from app.modules.orders.stock import OrdersStockPort
from app.modules.products import create_products_router
from app.modules.rbac.router import create_rbac_router
from app.modules.rbac.service import RbacService
from app.modules.settings import create_settings_router
from app.modules.settings.service import SettingsService
from app.modules.settings.types import DEFAULT_WAREHOUSE_SETTING
from app.modules.users import create_users_router
from app.modules.warehouse import create_stock_operations, create_warehouse_router
from app.realtime.gateway import RealtimeGateway
from app.realtime.topics import (
    RealtimeEntityType,
    collection_topic_for_entity,
    entity_topic,
    is_realtime_entity_type,
    topic_permission_requirement,
)
from app.realtime.types import AuthContextLike

logger = get_logger("container")

API_PREFIX = "/api/v1"


def _to_realtime_payload(event: DomainEvent) -> dict[str, Any]:
    return {
        "eventType": event.event_type,
        "entityType": event.entity_type,
        "entityId": event.entity_id,
        "actorId": event.actor_id,
        "payload": event.payload,
    }


class RealtimeSubscriber:
    """Forwards a committed change to connected realtime clients."""

    name = "realtime"

    def __init__(self, gateway: RealtimeGateway) -> None:
        self._gateway = gateway

    @staticmethod
    def _topics_for(event: DomainEvent) -> list[str]:
        """The streams one committed change belongs on: the collection, and the record."""
        topics: list[str] = []
        collection = collection_topic_for_entity(event.entity_type)
        if collection is not None:
            topics.append(collection)

        if is_realtime_entity_type(event.entity_type):
            entity_type = cast(RealtimeEntityType, event.entity_type)
            topics.append(entity_topic(entity_type, event.entity_id))

        return topics

    async def notify(self, event: DomainEvent) -> None:
        # Every topic is attempted, even after one of them fails: a client
        # watching a single record must still hear the change when it was the
        # collection stream that broke, and the other way round. The first
        # failure is kept and re-raised once the rest have been delivered, so
        # the fan-out still reports it instead of losing it to a bare except.
        payload = _to_realtime_payload(event)
        failure: BaseException | None = None
        for topic in self._topics_for(event):
            try:
                await self._gateway.publish(topic, payload)
            except Exception as error:
                failure = failure or error

        if failure is not None:
            raise failure


class EventLogSubscriber:
    """Appends a committed change to the durable event log."""

    name = "event-log"

    def __init__(self, events: EventStoreService) -> None:
        self._events = events

    async def notify(self, event: DomainEvent) -> None:
        await self._events.append(event)


class FanOutPublisher(DomainEventSubject):
    """The subject, pre-configured with the two default secondary consumers.

    Both are best-effort by contract, so the work is detached from the request
    that produced it and every failure is contained per-subscriber: an
    unreachable event log or a slow subscriber must never surface to the
    caller whose transaction already committed. A further consumer can be
    registered with ``subscribe`` without touching either subscriber above.
    """

    def __init__(self, events: EventStoreService, gateway: RealtimeGateway) -> None:
        super().__init__()
        # Realtime first, and the log strictly after it: a slow or degraded
        # document store must not delay the fan-out to connected clients.
        self.subscribe(RealtimeSubscriber(gateway))
        self.subscribe(EventLogSubscriber(events))


@dataclass(slots=True)
class Container:
    """Everything the process owns for its whole lifetime."""

    settings: Settings
    database: Database
    redis: PrefixedRedis
    cache: CacheService | NoopCacheService
    event_store: EventStore
    events: EventStoreService
    gateway: RealtimeGateway
    publisher: FanOutPublisher
    orders_stock: OrdersStockPort
    delivery_client: DeliveryClient
    ai_config: AiConfig
    ai_provider: AiProvider
    call_provider_config: CallProviderConfig
    call_sync_batch_size: int
    routers: list[tuple[str, APIRouter]] = field(default_factory=list)
    readiness_checks: list[ReadinessCheck] = field(default_factory=list)


def build_container(settings: Settings) -> Container:
    """Wires the object graph without opening a single connection.

    Clients are constructed lazily by their libraries, so nothing here touches
    the network; the lifespan is what actually connects.
    """
    database = Database(settings)
    redis = create_redis_client(settings)
    # Which family of implementations runs — offline stand-ins or the real
    # thing, per the settings below — is decided once here, instead of the AI
    # provider, the delivery client and the cache each noticing their own
    # setting independently.
    infra = create_infra_stack(settings, redis, logger)
    cache = infra.cache
    event_store = EventStore(settings)
    events = EventStoreService(event_store)
    auth_config = auth_config_from_settings(settings)

    async def verify_access_token(token: str) -> AuthContextLike:
        # The gateway runs outside the request dependency graph, so it opens a
        # short-lived session of its own for the handshake.
        async with database.session_factory() as session:
            return await AuthService(session, auth_config).authenticate(token)

    async def can_subscribe(auth: AuthContextLike, topic: str) -> bool:
        requirement = topic_permission_requirement(topic)
        if requirement is None:
            return False

        async with database.session_factory() as session:
            rbac = RbacService(session, cache, settings.cache_ttl_seconds)
            scope = await rbac.get_permission_scope(
                auth.user_id, requirement.resource, requirement.action
            )

        # Any grant opens the topic; the breadth is not narrowed here because
        # the events themselves carry no ownership the gateway could filter on.
        # What a subscriber may *read* is still decided by the HTTP API.
        return scope is not None

    gateway = RealtimeGateway(
        ws_path=settings.ws_path,
        verify_access_token=verify_access_token,
        can_subscribe=can_subscribe,
    )
    publisher = FanOutPublisher(events, gateway)

    async def resolve_warehouse_id(session: AsyncSession) -> uuid.UUID | None:
        """Which warehouse an order draws on — a deployment choice, not a field.

        Runs on the order's own session, so it observes the same snapshot as the
        stock writes. An inactive warehouse is returned deliberately: the stock
        guard then reports it as inactive, which is more useful than a generic
        "nothing configured".
        """
        code = await SettingsService(session, cache, settings.cache_ttl_seconds).get(
            DEFAULT_WAREHOUSE_SETTING
        )
        if not isinstance(code, str):
            return None
        warehouse_id: uuid.UUID | None = await session.scalar(
            select(Warehouse.id).where(Warehouse.code == code)
        )
        return warehouse_id

    # Both adapters, and their configuration, come from the infra profile
    # decided above: the client is built once per process, not per request, so
    # the circuit breaker's failure count outlives the request that
    # incremented it, and the "running on the mock" warning fires exactly once.
    delivery_client = infra.delivery_client
    ai_config = infra.ai_config
    ai_provider = infra.ai_provider
    call_provider_config = infra.call_provider_config

    return Container(
        settings=settings,
        database=database,
        redis=redis,
        cache=cache,
        event_store=event_store,
        events=events,
        gateway=gateway,
        publisher=publisher,
        orders_stock=OrdersStockPort(
            operations=create_stock_operations(publisher),
            resolve_warehouse_id=resolve_warehouse_id,
        ),
        delivery_client=delivery_client,
        ai_config=ai_config,
        ai_provider=ai_provider,
        call_provider_config=call_provider_config,
        call_sync_batch_size=settings.call_sync_batch_size,
        routers=[
            (f"{API_PREFIX}/auth", create_auth_router()),
            (f"{API_PREFIX}/rbac", create_rbac_router()),
            (f"{API_PREFIX}/users", create_users_router()),
            (f"{API_PREFIX}/audit", create_audit_router()),
            (f"{API_PREFIX}/helpdesk", create_helpdesk_router()),
            (f"{API_PREFIX}/calls", create_calls_router()),
            (f"{API_PREFIX}/contacts", create_contacts_router()),
            (f"{API_PREFIX}/deals", create_deals_router()),
            (f"{API_PREFIX}/products", create_products_router()),
            (f"{API_PREFIX}/orders", create_orders_router()),
            (f"{API_PREFIX}/warehouse", create_warehouse_router()),
            (f"{API_PREFIX}/settings", create_settings_router()),
            (f"{API_PREFIX}/analytics", create_analytics_router()),
            (f"{API_PREFIX}/integrations", create_integrations_router()),
            (f"{API_PREFIX}/ai", create_ai_router()),
        ],
        readiness_checks=[
            create_database_readiness_check(database),
            create_cache_readiness_check(redis),
            create_event_store_readiness_check(event_store),
        ],
    )
