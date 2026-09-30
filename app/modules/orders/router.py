"""HTTP surface of the orders module.

The status has an endpoint of its own. Folding it into ``PATCH`` would make an
illegal move look like an ordinary field assignment, and would leave no obvious
place for the stock movements a status change drags along; a transition is an
operation, so it is posted rather than patched.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.openapi import refusals
from app.core.responses import Envelope, Page
from app.db.enums import PermissionScope
from app.events.dependencies import PublisherDep
from app.modules.audit import AuditService
from app.modules.auth.dependencies import CurrentAuth, SessionDep
from app.modules.auth.types import AuthContext
from app.modules.orders.schemas import (
    AddOrderItemRequest,
    CreateOrderRequest,
    OrderListParams,
    OrderOut,
    TransitionOrderRequest,
    UpdateOrderItemRequest,
    UpdateOrderRequest,
)
from app.modules.orders.service import OrdersService
from app.modules.orders.stock import OrdersStockPort
from app.modules.orders.types import OrderAccess
from app.modules.rbac.dependencies import require_permission

ReadScope = Annotated[PermissionScope, Depends(require_permission("orders", "read"))]
WriteScope = Annotated[PermissionScope, Depends(require_permission("orders", "write"))]
DeleteScope = Annotated[PermissionScope, Depends(require_permission("orders", "delete"))]

ListParams = Annotated[OrderListParams, Query()]
#: Optimistic locking on a request that carries no body.
VersionQuery = Annotated[int, Query(ge=1)]


def get_orders_stock(request: Request) -> OrdersStockPort | None:
    """The stock implementation, if this deployment wired one in.

    Read from the application state rather than imported, so the orders module
    never names the warehouse module: the composition root supplies the port,
    and a process assembled without a warehouse simply has none.
    """
    port = getattr(request.app.state, "orders_stock", None)
    return port if isinstance(port, OrdersStockPort) else None


StockDep = Annotated[OrdersStockPort | None, Depends(get_orders_stock)]


def get_orders_service(
    session: SessionDep, publisher: PublisherDep, stock: StockDep
) -> OrdersService:
    # The audit service shares the request session, so an order change and its
    # trail entry commit together or not at all.
    return OrdersService(session, AuditService(session), publisher, stock)


OrdersServiceDep = Annotated[OrdersService, Depends(get_orders_service)]


def _access(auth: AuthContext, scope: PermissionScope, request: Request) -> OrderAccess:
    """Who is acting, how wide their grant is, and from where."""
    client = request.client
    return OrderAccess(
        actor_id=auth.user_id,
        scope=scope,
        ip_address=client.host if client is not None else None,
    )


def create_orders_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["Orders"])

    @router.get("", summary="Переглянути замовлення", responses=refusals(401, 403))
    async def list_orders(
        request: Request,
        auth: CurrentAuth,
        scope: ReadScope,
        service: OrdersServiceDep,
        params: ListParams,
    ) -> Envelope[Page[OrderOut]]:
        items, total = await service.list(_access(auth, scope, request), params)
        return Envelope(
            data=Page(items=items, page=params.page, page_size=params.page_size, total=total)
        )

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        summary="Створити замовлення",
        responses=refusals(401, 403, 404, 409),
    )
    async def create_order(
        request: Request,
        payload: CreateOrderRequest,
        auth: CurrentAuth,
        scope: WriteScope,
        service: OrdersServiceDep,
    ) -> Envelope[OrderOut]:
        return Envelope(data=await service.create(_access(auth, scope, request), payload))

    @router.post(
        "/{id}/duplicate",
        status_code=status.HTTP_201_CREATED,
        summary="Повторити замовлення",
        responses=refusals(401, 403, 404, 409),
    )
    async def duplicate_order(
        id: uuid.UUID,  # noqa: A002
        request: Request,
        auth: CurrentAuth,
        scope: WriteScope,
        service: OrdersServiceDep,
    ) -> Envelope[OrderOut]:
        return Envelope(data=await service.duplicate(_access(auth, scope, request), id))

    @router.get("/{id}", summary="Отримати замовлення", responses=refusals(401, 403, 404))
    async def get_order(
        id: uuid.UUID,  # noqa: A002
        request: Request,
        auth: CurrentAuth,
        scope: ReadScope,
        service: OrdersServiceDep,
    ) -> Envelope[OrderOut]:
        return Envelope(data=await service.get_by_id(_access(auth, scope, request), id))

    @router.patch("/{id}", summary="Оновити замовлення", responses=refusals(401, 403, 404, 409))
    # A path parameter, a body and the three standard dependencies; there is
    # nothing here to bundle that would not just hide a parameter.
    async def update_order(  # noqa: PLR0913, PLR0917
        id: uuid.UUID,  # noqa: A002
        payload: UpdateOrderRequest,
        request: Request,
        auth: CurrentAuth,
        scope: WriteScope,
        service: OrdersServiceDep,
    ) -> Envelope[OrderOut]:
        return Envelope(data=await service.update(_access(auth, scope, request), id, payload))

    @router.post(
        "/{id}/items",
        status_code=status.HTTP_201_CREATED,
        summary="Додати позицію до замовлення",
        responses=refusals(401, 403, 404, 409),
    )
    async def add_order_item(  # noqa: PLR0913, PLR0917
        id: uuid.UUID,  # noqa: A002
        payload: AddOrderItemRequest,
        request: Request,
        auth: CurrentAuth,
        scope: WriteScope,
        service: OrdersServiceDep,
    ) -> Envelope[OrderOut]:
        return Envelope(data=await service.add_item(_access(auth, scope, request), id, payload))

    @router.patch(
        "/{id}/items/{item_id}",
        summary="Оновити позицію замовлення",
        responses=refusals(401, 403, 404, 409),
    )
    async def update_order_item(  # noqa: PLR0913, PLR0917
        id: uuid.UUID,  # noqa: A002
        item_id: uuid.UUID,
        payload: UpdateOrderItemRequest,
        request: Request,
        auth: CurrentAuth,
        scope: WriteScope,
        service: OrdersServiceDep,
    ) -> Envelope[OrderOut]:
        return Envelope(
            data=await service.update_item(_access(auth, scope, request), id, item_id, payload)
        )

    @router.delete(
        "/{id}/items/{item_id}",
        summary="Видалити позицію із замовлення",
        responses=refusals(401, 403, 404, 409),
    )
    async def remove_order_item(  # noqa: PLR0913, PLR0917
        id: uuid.UUID,  # noqa: A002
        item_id: uuid.UUID,
        version: VersionQuery,
        request: Request,
        auth: CurrentAuth,
        scope: WriteScope,
        service: OrdersServiceDep,
    ) -> Envelope[OrderOut]:
        return Envelope(
            data=await service.remove_item(_access(auth, scope, request), id, item_id, version)
        )

    @router.post(
        "/{id}/transitions",
        summary="Змінити статус замовлення",
        responses=refusals(401, 403, 404, 409),
    )
    async def transition_order(  # noqa: PLR0913, PLR0917
        id: uuid.UUID,  # noqa: A002
        payload: TransitionOrderRequest,
        request: Request,
        auth: CurrentAuth,
        scope: WriteScope,
        service: OrdersServiceDep,
    ) -> Envelope[OrderOut]:
        return Envelope(data=await service.transition(_access(auth, scope, request), id, payload))

    @router.delete(
        "/{id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        summary="Видалити замовлення",
        responses=refusals(401, 403, 404, 409),
    )
    async def delete_order(  # noqa: PLR0913, PLR0917
        id: uuid.UUID,  # noqa: A002
        version: VersionQuery,
        request: Request,
        auth: CurrentAuth,
        scope: DeleteScope,
        service: OrdersServiceDep,
    ) -> Response:
        await service.delete(_access(auth, scope, request), id, version)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


__all__ = [
    "OrdersServiceDep",
    "create_orders_router",
    "get_orders_service",
    "get_orders_stock",
]
