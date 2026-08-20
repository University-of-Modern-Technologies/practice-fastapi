"""HTTP surface of the deals module.

The stage lives behind its own endpoint. ``PATCH`` edits a deal, ``POST
/{id}/transitions`` moves it — two verbs because they are two decisions: one is
the client's to make, the other the pipeline's to allow.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.responses import Envelope, Page
from app.db.enums import PermissionScope
from app.events.dependencies import PublisherDep
from app.modules.auth.dependencies import CurrentAuth, SessionDep
from app.modules.deals.schemas import (
    CreateDealRequest,
    DealListParams,
    DealOut,
    TransitionDealRequest,
    UpdateDealRequest,
)
from app.modules.deals.service import DealsService
from app.modules.deals.types import DealAccess
from app.modules.rbac.dependencies import require_permission

ReadScope = Annotated[PermissionScope, Depends(require_permission("deals", "read"))]
WriteScope = Annotated[PermissionScope, Depends(require_permission("deals", "write"))]
DeleteScope = Annotated[PermissionScope, Depends(require_permission("deals", "delete"))]

ListParams = Annotated[DealListParams, Query()]
DealVersion = Annotated[int, Query(ge=1)]


def get_deals_service(session: SessionDep, publisher: PublisherDep) -> DealsService:
    return DealsService(session, publisher)


DealsServiceDep = Annotated[DealsService, Depends(get_deals_service)]


def _client_ip(request: Request) -> str | None:
    """The address the audit trail records the change against."""
    return request.client.host if request.client is not None else None


def _access(auth: CurrentAuth, request: Request, scope: PermissionScope) -> DealAccess:
    return DealAccess(actor_id=auth.user_id, scope=scope, ip_address=_client_ip(request))


# Identity, breadth of grant and client address are resolved together, so a
# handler takes one argument instead of three and cannot forget one of them.
async def get_read_access(auth: CurrentAuth, request: Request, scope: ReadScope) -> DealAccess:
    return _access(auth, request, scope)


async def get_write_access(auth: CurrentAuth, request: Request, scope: WriteScope) -> DealAccess:
    return _access(auth, request, scope)


async def get_delete_access(auth: CurrentAuth, request: Request, scope: DeleteScope) -> DealAccess:
    return _access(auth, request, scope)


ReadAccess = Annotated[DealAccess, Depends(get_read_access)]
WriteAccess = Annotated[DealAccess, Depends(get_write_access)]
DeleteAccess = Annotated[DealAccess, Depends(get_delete_access)]


def create_deals_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["Deals"])

    @router.get("", summary="Переглянути угоди")
    async def list_deals(
        access: ReadAccess,
        service: DealsServiceDep,
        params: ListParams,
    ) -> Envelope[Page[DealOut]]:
        items, total = await service.list_deals(access, params)
        return Envelope(
            data=Page(items=items, page=params.page, page_size=params.page_size, total=total)
        )

    @router.post("", status_code=status.HTTP_201_CREATED, summary="Створити угоду")
    async def create_deal(
        payload: CreateDealRequest,
        access: WriteAccess,
        service: DealsServiceDep,
    ) -> Envelope[DealOut]:
        return Envelope(data=await service.create(access, payload))

    @router.get("/{id}", summary="Отримати угоду")
    async def get_deal(
        id: uuid.UUID,  # noqa: A002
        access: ReadAccess,
        service: DealsServiceDep,
    ) -> Envelope[DealOut]:
        return Envelope(data=await service.get_by_id(access, id))

    @router.patch("/{id}", summary="Оновити угоду без зміни stage")
    async def update_deal(
        id: uuid.UUID,  # noqa: A002
        payload: UpdateDealRequest,
        access: WriteAccess,
        service: DealsServiceDep,
    ) -> Envelope[DealOut]:
        return Envelope(data=await service.update(access, id, payload))

    @router.post(
        "/{id}/transitions",
        tags=["Deal transitions"],
        summary="Перевести угоду на інший stage",
        description="Дозволені переходи: LEAD → QUALIFIED, QUALIFIED → PROPOSAL, "
        "PROPOSAL → WON/LOST.",
    )
    async def transition_deal(
        id: uuid.UUID,  # noqa: A002
        payload: TransitionDealRequest,
        access: WriteAccess,
        service: DealsServiceDep,
    ) -> Envelope[DealOut]:
        return Envelope(data=await service.transition(access, id, payload))

    @router.delete(
        "/{id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        summary="Видалити угоду",
    )
    async def delete_deal(
        id: uuid.UUID,  # noqa: A002
        version: DealVersion,
        access: DeleteAccess,
        service: DealsServiceDep,
    ) -> Response:
        await service.delete(access, id, version)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
