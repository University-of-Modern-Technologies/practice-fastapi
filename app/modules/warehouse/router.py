"""HTTP surface of warehouses, stock and movements.

Movements are append-only by design: there is no update or delete verb for them,
so the ledger can only grow. A mistake is corrected by recording a compensating
adjustment, never by rewriting history.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.openapi import refusals
from app.core.responses import Envelope, Page
from app.db.enums import PermissionScope
from app.events.dependencies import PublisherDep
from app.modules.auth.dependencies import CurrentAuth, SessionDep
from app.modules.rbac.dependencies import require_permission
from app.modules.warehouse.schemas import (
    AdjustStockRequest,
    CreateWarehouseRequest,
    IssueStockRequest,
    MovementListParams,
    ReceiveStockRequest,
    ReleaseStockRequest,
    ReserveStockRequest,
    StockLevelOut,
    StockListParams,
    StockMovementOut,
    UpdateWarehouseRequest,
    WarehouseListParams,
    WarehouseOut,
)
from app.modules.warehouse.service import WarehouseService
from app.modules.warehouse.types import WAREHOUSE_RESOURCE, WarehouseAccess

ReadScope = Annotated[PermissionScope, Depends(require_permission(WAREHOUSE_RESOURCE, "read"))]
WriteScope = Annotated[PermissionScope, Depends(require_permission(WAREHOUSE_RESOURCE, "write"))]


def _access(request: Request, actor_id: uuid.UUID, scope: PermissionScope) -> WarehouseAccess:
    client = request.client
    return WarehouseAccess(
        actor_id=actor_id, scope=scope, ip_address=client.host if client is not None else None
    )


def get_read_access(request: Request, auth: CurrentAuth, scope: ReadScope) -> WarehouseAccess:
    """Admission plus identity in one dependency.

    Bundled deliberately: every handler needs the caller, their grant and the
    address the change came from, and passing one object keeps the audit trail
    from depending on a handler remembering to forward three of them.
    """
    return _access(request, auth.user_id, scope)


def get_write_access(request: Request, auth: CurrentAuth, scope: WriteScope) -> WarehouseAccess:
    return _access(request, auth.user_id, scope)


def get_warehouse_service(session: SessionDep, publisher: PublisherDep) -> WarehouseService:
    return WarehouseService(session, publisher)


ReadAccess = Annotated[WarehouseAccess, Depends(get_read_access)]
WriteAccess = Annotated[WarehouseAccess, Depends(get_write_access)]
ServiceDep = Annotated[WarehouseService, Depends(get_warehouse_service)]
WarehouseParams = Annotated[WarehouseListParams, Query()]
StockParams = Annotated[StockListParams, Query()]
MovementParams = Annotated[MovementListParams, Query()]


def create_warehouse_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter()

    @router.get(
        "/warehouses",
        tags=["Warehouses"],
        summary="Переглянути склади",
        responses=refusals(401, 403),
    )
    async def list_warehouses(
        _access: ReadAccess, service: ServiceDep, params: WarehouseParams
    ) -> Envelope[Page[WarehouseOut]]:
        items, total = await service.list_warehouses(params)
        return Envelope(
            data=Page(items=items, page=params.page, page_size=params.page_size, total=total)
        )

    @router.get(
        "/warehouses/{id}",
        tags=["Warehouses"],
        summary="Отримати склад",
        responses=refusals(401, 403, 404),
    )
    async def get_warehouse(
        id: uuid.UUID,  # noqa: A002
        _access: ReadAccess,
        service: ServiceDep,
    ) -> Envelope[WarehouseOut]:
        return Envelope(data=await service.get_warehouse(id))

    @router.post(
        "/warehouses",
        tags=["Warehouses"],
        status_code=status.HTTP_201_CREATED,
        summary="Створити склад",
        responses=refusals(401, 403, 409),
    )
    async def create_warehouse(
        payload: CreateWarehouseRequest, access: WriteAccess, service: ServiceDep
    ) -> Envelope[WarehouseOut]:
        return Envelope(data=await service.create_warehouse(access, payload))

    @router.patch(
        "/warehouses/{id}",
        tags=["Warehouses"],
        summary="Оновити склад",
        responses=refusals(401, 403, 404),
    )
    async def update_warehouse(
        id: uuid.UUID,  # noqa: A002
        payload: UpdateWarehouseRequest,
        access: WriteAccess,
        service: ServiceDep,
    ) -> Envelope[WarehouseOut]:
        return Envelope(data=await service.update_warehouse(access, id, payload))

    @router.get(
        "/stock", tags=["Stock"], summary="Переглянути рівні запасів", responses=refusals(401, 403)
    )
    async def list_stock(
        _access: ReadAccess, service: ServiceDep, params: StockParams
    ) -> Envelope[Page[StockLevelOut]]:
        items, total = await service.list_stock(params)
        return Envelope(
            data=Page(items=items, page=params.page, page_size=params.page_size, total=total)
        )

    @router.get(
        "/stock/{warehouse_id}/{product_id}",
        tags=["Stock"],
        summary="Отримати рівень запасів позиції на складі",
        responses=refusals(401, 403, 404),
    )
    async def get_stock(
        warehouse_id: uuid.UUID,
        product_id: uuid.UUID,
        _access: ReadAccess,
        service: ServiceDep,
    ) -> Envelope[StockLevelOut]:
        return Envelope(data=await service.get_stock(warehouse_id, product_id))

    @router.post(
        "/stock/receive",
        tags=["Stock"],
        summary="Оприбуткувати запас",
        responses=refusals(401, 403, 404, 409),
    )
    async def receive_stock(
        payload: ReceiveStockRequest, access: WriteAccess, service: ServiceDep
    ) -> Envelope[StockLevelOut]:
        return Envelope(data=await service.receive(access, payload))

    @router.post(
        "/stock/issue",
        tags=["Stock"],
        summary="Списати запас",
        responses=refusals(401, 403, 404, 409),
    )
    async def issue_stock(
        payload: IssueStockRequest, access: WriteAccess, service: ServiceDep
    ) -> Envelope[StockLevelOut]:
        return Envelope(data=await service.issue(access, payload))

    @router.post(
        "/stock/reserve",
        tags=["Stock"],
        summary="Зарезервувати запас",
        responses=refusals(401, 403, 404, 409),
    )
    async def reserve_stock(
        payload: ReserveStockRequest, access: WriteAccess, service: ServiceDep
    ) -> Envelope[StockLevelOut]:
        return Envelope(data=await service.reserve(access, payload))

    @router.post(
        "/stock/release",
        tags=["Stock"],
        summary="Зняти резерв",
        responses=refusals(401, 403, 404, 409),
    )
    async def release_stock(
        payload: ReleaseStockRequest, access: WriteAccess, service: ServiceDep
    ) -> Envelope[StockLevelOut]:
        return Envelope(data=await service.release(access, payload))

    @router.post(
        "/stock/adjust",
        tags=["Stock"],
        summary="Скоригувати запас",
        responses=refusals(401, 403, 404, 409),
    )
    async def adjust_stock(
        payload: AdjustStockRequest, access: WriteAccess, service: ServiceDep
    ) -> Envelope[StockLevelOut]:
        return Envelope(data=await service.adjust(access, payload))

    @router.get(
        "/movements",
        tags=["Stock movements"],
        summary="Переглянути журнал рухів запасів",
        responses=refusals(401, 403),
    )
    async def list_movements(
        _access: ReadAccess, service: ServiceDep, params: MovementParams
    ) -> Envelope[Page[StockMovementOut]]:
        items, total = await service.list_movements(params)
        return Envelope(
            data=Page(items=items, page=params.page, page_size=params.page_size, total=total)
        )

    return router
