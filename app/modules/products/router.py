"""HTTP surface of the product catalogue.

Every write carries the version it is editing, so the endpoints are safe to
expose to two people looking at the same screen: the second write is rejected
with a conflict instead of quietly overwriting the first.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from app.core.responses import Envelope, Page
from app.db.enums import PermissionScope
from app.events.dependencies import PublisherDep
from app.modules.auth.dependencies import CurrentAuth, SessionDep
from app.modules.products.schemas import (
    CreateProductRequest,
    ProductListParams,
    ProductOut,
    UpdateProductRequest,
)
from app.modules.products.service import ProductsService
from app.modules.products.types import ProductAccess
from app.modules.rbac.dependencies import require_permission

RESOURCE = "products"


def get_products_service(session: SessionDep, publisher: PublisherDep) -> ProductsService:
    return ProductsService(session, publisher)


ProductsServiceDep = Annotated[ProductsService, Depends(get_products_service)]


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


def _require_access(action: str) -> Callable[..., Awaitable[ProductAccess]]:
    """Builds the dependency that admits a caller and describes them.

    Bundled into one value so a handler takes an access object instead of three
    separate parameters that always travel together.
    """
    permission = require_permission(RESOURCE, action)

    # The permission is a default rather than an ``Annotated`` member: postponed
    # annotations turn every hint into a string, and a string naming a local
    # closure is not something FastAPI can resolve at import.
    async def dependency(
        request: Request,
        auth: CurrentAuth,
        scope: PermissionScope = Depends(permission),
    ) -> ProductAccess:
        return ProductAccess(actor_id=auth.user_id, scope=scope, ip_address=_client_ip(request))

    return dependency


ReadAccess = Annotated[ProductAccess, Depends(_require_access("read"))]
WriteAccess = Annotated[ProductAccess, Depends(_require_access("write"))]
DeleteAccess = Annotated[ProductAccess, Depends(_require_access("delete"))]

ListParams = Annotated[ProductListParams, Query()]
ProductId = Annotated[uuid.UUID, Path()]
#: A delete carries its version in the query string: the request has no body.
DeleteVersion = Annotated[int, Query(ge=1)]


def create_products_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["Products"])

    @router.get("", summary="Переглянути каталог товарів")
    async def list_products(
        _access: ReadAccess,
        service: ProductsServiceDep,
        params: ListParams,
    ) -> Envelope[Page[ProductOut]]:
        items, total = await service.list(params)
        return Envelope(
            data=Page(items=items, page=params.page, page_size=params.page_size, total=total)
        )

    @router.post("", status_code=status.HTTP_201_CREATED, summary="Створити товар")
    async def create_product(
        payload: CreateProductRequest,
        access: WriteAccess,
        service: ProductsServiceDep,
    ) -> Envelope[ProductOut]:
        return Envelope(data=await service.create(access, payload))

    @router.get("/{product_id}", summary="Отримати товар")
    async def get_product(
        product_id: ProductId,
        _access: ReadAccess,
        service: ProductsServiceDep,
    ) -> Envelope[ProductOut]:
        return Envelope(data=await service.get_by_id(product_id))

    @router.patch("/{product_id}", summary="Оновити товар")
    async def update_product(
        product_id: ProductId,
        payload: UpdateProductRequest,
        access: WriteAccess,
        service: ProductsServiceDep,
    ) -> Envelope[ProductOut]:
        return Envelope(data=await service.update(access, product_id, payload))

    @router.delete(
        "/{product_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        summary="Видалити товар",
    )
    async def delete_product(
        product_id: ProductId,
        version: DeleteVersion,
        access: DeleteAccess,
        service: ProductsServiceDep,
    ) -> Response:
        await service.delete(access, product_id, version)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
