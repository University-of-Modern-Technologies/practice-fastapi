"""HTTP surface of the integrations module.

Four endpoints, one dependency: a delivery client whose circuit breaker has to
outlive the request that opened it. That is why the client is resolved from the
application rather than built per call — a breaker rebuilt on every request
would forget that the upstream is down and would keep sending traffic into it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, status

from app.core.responses import Envelope
from app.db.enums import PermissionScope
from app.modules.integrations.delivery.client import DeliveryClient
from app.modules.integrations.delivery.factory import (
    DEFAULT_QUOTE_CACHE_TTL_SECONDS,
    create_configured_delivery_client,
)
from app.modules.integrations.schemas import (
    CreateShipmentRequest,
    QuoteRequest,
    ShipmentId,
)
from app.modules.integrations.service import IntegrationsService
from app.modules.integrations.types import (
    DeliveryHealthDto,
    DeliveryQuoteDto,
    NoopQuoteCache,
    QuoteCachePort,
    ShipmentDto,
)
from app.modules.rbac.dependencies import require_permission

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


def get_integrations_service(
    client: DeliveryClientDep, cache: QuoteCacheDep
) -> IntegrationsService:
    return IntegrationsService(client, cache, DEFAULT_QUOTE_CACHE_TTL_SECONDS)


IntegrationsServiceDep = Annotated[IntegrationsService, Depends(get_integrations_service)]

#: Quotes, shipment status and integration health are all reads. Creating a
#: shipment dispatches a parcel, and is the only write in the module.
ReadScope = Annotated[PermissionScope, Depends(require_permission(RESOURCE, "read"))]
WriteScope = Annotated[PermissionScope, Depends(require_permission(RESOURCE, "write"))]

ShipmentIdParam = Annotated[ShipmentId, Path()]


def create_integrations_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["Integrations"])

    # Circuit state is an operational detail, so it stays behind the same read
    # permission as the rest of the module rather than being exposed publicly.
    @router.get("/health", summary="Стан інтеграції з перевізником")
    async def integration_health(
        _scope: ReadScope,
        service: IntegrationsServiceDep,
    ) -> Envelope[DeliveryHealthDto]:
        return Envelope(data=service.health())

    @router.post("/delivery/quotes", summary="Розрахувати вартість доставки")
    async def create_quote(
        payload: QuoteRequest,
        _scope: ReadScope,
        service: IntegrationsServiceDep,
    ) -> Envelope[DeliveryQuoteDto]:
        return Envelope(data=await service.request_quote(payload))

    @router.post(
        "/delivery/shipments",
        status_code=status.HTTP_201_CREATED,
        summary="Створити відправлення",
    )
    async def create_shipment(
        payload: CreateShipmentRequest,
        _scope: WriteScope,
        service: IntegrationsServiceDep,
    ) -> Envelope[ShipmentDto]:
        return Envelope(data=await service.create_shipment(payload))

    @router.get("/delivery/shipments/{id}", summary="Статус відправлення")
    async def get_shipment(
        id: ShipmentIdParam,  # noqa: A002 — the published path parameter is `id`
        _scope: ReadScope,
        service: IntegrationsServiceDep,
    ) -> Envelope[ShipmentDto]:
        return Envelope(data=await service.get_shipment(id))

    return router
