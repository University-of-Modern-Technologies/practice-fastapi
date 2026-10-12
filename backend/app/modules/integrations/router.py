"""HTTP surface of the integrations module.

Four endpoints, one dependency: a delivery client whose circuit breaker has to
outlive the request that opened it. That is why the client is resolved from the
application rather than built per call — a breaker rebuilt on every request
would forget that the upstream is down and would keep sending traffic into it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, status

from app.core.openapi import refusals
from app.core.responses import Envelope
from app.db.enums import PermissionScope
from app.modules.auth.dependencies import CurrentAuth
from app.modules.auth.dependencies import SettingsDep as AppSettingsDep
from app.modules.integrations.delivery.client import DeliveryClient
from app.modules.integrations.delivery.factory import create_configured_delivery_client
from app.modules.integrations.schemas import (
    CreateShipmentRequest,
    QuoteRequest,
    ShipmentId,
)
from app.modules.integrations.service import IntegrationsService
from app.modules.integrations.types import (
    DeliveryHealthDto,
    DeliveryQuoteDto,
    FindOrderForShipment,
    NoopQuoteCache,
    QuoteCachePort,
    ShipmentAccess,
    ShipmentDto,
)
from app.modules.rbac.dependencies import RbacServiceDep, require_permission

RESOURCE = "integrations"


def get_delivery_client(request: Request) -> DeliveryClient:
    """The client this application talks to the carrier with.

    The composition root publishes one on the application state. When it has not
    — a fresh checkout, a test application — a stub-backed client is built once
    and published here, so the whole feature works with no configuration and the
    breaker still accumulates state across requests.
    """
    client = getattr(request.app.state, "delivery_client", None)
    if isinstance(client, DeliveryClient):
        return client

    client = create_configured_delivery_client()
    request.app.state.delivery_client = client
    return client


def get_quote_cache(request: Request) -> QuoteCachePort:
    """The cache backend if one was wired in, otherwise a cache that stores nothing."""
    cache = getattr(request.app.state, "cache", None)
    if cache is None:
        return NoopQuoteCache()
    return cache  # type: ignore[no-any-return]


DeliveryClientDep = Annotated[DeliveryClient, Depends(get_delivery_client)]
QuoteCacheDep = Annotated[QuoteCachePort, Depends(get_quote_cache)]


def get_order_lookup(request: Request) -> FindOrderForShipment | None:
    """The order lookup the composition root published, if it published one.

    Without it the service finds no order and refuses every delivery — the safe
    default for a check whose whole point is not to ship an unchecked order.
    """
    lookup: FindOrderForShipment | None = getattr(
        request.app.state, "find_order_for_shipment", None
    )
    return lookup


OrderLookupDep = Annotated[FindOrderForShipment | None, Depends(get_order_lookup)]


def get_integrations_service(
    client: DeliveryClientDep,
    cache: QuoteCacheDep,
    config: AppSettingsDep,
    find_order: OrderLookupDep,
) -> IntegrationsService:
    # How long a quote may be served from the cache is a deployment setting.
    return IntegrationsService(
        client,
        cache,
        config.delivery_quote_cache_ttl_seconds,
        find_order_for_shipment=find_order,
    )


IntegrationsServiceDep = Annotated[IntegrationsService, Depends(get_integrations_service)]


async def get_shipment_access(auth: CurrentAuth, rbac: RbacServiceDep) -> ShipmentAccess:
    """Which orders the caller may ship.

    A delivery names an order, so whether it is visible is decided by the
    caller's ``orders:read`` grant, at its own breadth.
    """
    return ShipmentAccess(
        actor_id=auth.user_id,
        order_scope=await rbac.get_permission_scope(auth.user_id, "orders", "read"),
    )


ShipmentAccessDep = Annotated[ShipmentAccess, Depends(get_shipment_access)]

#: Quotes, shipment status and integration health are all reads. Creating a
#: shipment dispatches a parcel, and is the only write in the module.
ReadScope = Annotated[PermissionScope, Depends(require_permission(RESOURCE, "read"))]
WriteScope = Annotated[PermissionScope, Depends(require_permission(RESOURCE, "write"))]

ShipmentIdParam = Annotated[ShipmentId, Path()]


def create_integrations_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter()

    # Circuit state is an operational detail, so it stays behind the same read
    # permission as the rest of the module rather than being exposed publicly.
    @router.get(
        "/health",
        tags=["Integrations"],
        summary="Стан інтеграції з перевізником",
        responses=refusals(401, 403),
    )
    async def integration_health(
        _scope: ReadScope,
        service: IntegrationsServiceDep,
    ) -> Envelope[DeliveryHealthDto]:
        return Envelope(data=service.health())

    @router.post(
        "/delivery/quotes",
        tags=["Delivery"],
        summary="Розрахувати вартість доставки",
        responses=refusals(401, 403, 404, 409, 422, 502, 503, 504),
    )
    async def create_quote(
        payload: QuoteRequest,
        _scope: ReadScope,
        access: ShipmentAccessDep,
        service: IntegrationsServiceDep,
    ) -> Envelope[DeliveryQuoteDto]:
        return Envelope(data=await service.request_quote(access, payload))

    @router.post(
        "/delivery/shipments",
        status_code=status.HTTP_201_CREATED,
        tags=["Delivery"],
        summary="Створити відправлення",
        responses=refusals(401, 403, 404, 409, 422, 502, 503, 504),
    )
    async def create_shipment(
        payload: CreateShipmentRequest,
        _scope: WriteScope,
        access: ShipmentAccessDep,
        service: IntegrationsServiceDep,
    ) -> Envelope[ShipmentDto]:
        return Envelope(data=await service.create_shipment(access, payload))

    @router.get(
        "/delivery/shipments/{id}",
        tags=["Delivery"],
        summary="Статус відправлення",
        responses=refusals(401, 403, 404, 422, 502, 503, 504),
    )
    async def get_shipment(
        id: ShipmentIdParam,  # noqa: A002 — the published path parameter is `id`
        _scope: ReadScope,
        service: IntegrationsServiceDep,
    ) -> Envelope[ShipmentDto]:
        return Envelope(data=await service.get_shipment(id))

    return router
