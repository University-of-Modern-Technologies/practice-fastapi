"""HTTP surface of the helpdesk module.

The status lives behind its own endpoint. ``PATCH`` edits a ticket, ``POST
/{id}/transitions`` moves it — two verbs because they are two decisions: one is
the client's to make, the other the lifecycle's to allow.

The paths are spelled ``/tickets`` rather than left bare, because the module is
mounted under the resource it guards — ``/api/v1/helpdesk`` — and a ticket is
one of the things a helpdesk keeps, not the only one it could ever keep.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.openapi import refusals
from app.core.responses import Envelope, Page
from app.db.enums import PermissionScope
from app.events.dependencies import PublisherDep
from app.modules.auth.dependencies import CurrentAuth, SessionDep
from app.modules.helpdesk.schemas import (
    CreateTicketRequest,
    TicketListParams,
    TicketOut,
    TransitionTicketRequest,
    UpdateTicketRequest,
)
from app.modules.helpdesk.service import HelpdeskService
from app.modules.helpdesk.types import TicketAccess
from app.modules.rbac.dependencies import require_permission

ReadScope = Annotated[PermissionScope, Depends(require_permission("helpdesk", "read"))]
WriteScope = Annotated[PermissionScope, Depends(require_permission("helpdesk", "write"))]
DeleteScope = Annotated[PermissionScope, Depends(require_permission("helpdesk", "delete"))]

ListParams = Annotated[TicketListParams, Query()]
TicketVersion = Annotated[int, Query(ge=1)]


def get_helpdesk_service(session: SessionDep, publisher: PublisherDep) -> HelpdeskService:
    return HelpdeskService(session, publisher)


HelpdeskServiceDep = Annotated[HelpdeskService, Depends(get_helpdesk_service)]


def _client_ip(request: Request) -> str | None:
    """The address the audit trail records the change against.

    Read from the connection rather than from a forwarded header: the header is
    caller-controlled, and an audit entry that records whatever the client
    claimed is worse than one that records nothing.
    """
    return request.client.host if request.client is not None else None


def _access(auth: CurrentAuth, request: Request, scope: PermissionScope) -> TicketAccess:
    return TicketAccess(actor_id=auth.user_id, scope=scope, ip_address=_client_ip(request))


# Identity, breadth of grant and client address are resolved together, so a
# handler takes one argument instead of three and cannot forget one of them.
async def get_read_access(auth: CurrentAuth, request: Request, scope: ReadScope) -> TicketAccess:
    return _access(auth, request, scope)


async def get_write_access(auth: CurrentAuth, request: Request, scope: WriteScope) -> TicketAccess:
    return _access(auth, request, scope)


async def get_delete_access(
    auth: CurrentAuth, request: Request, scope: DeleteScope
) -> TicketAccess:
    return _access(auth, request, scope)


ReadAccess = Annotated[TicketAccess, Depends(get_read_access)]
WriteAccess = Annotated[TicketAccess, Depends(get_write_access)]
DeleteAccess = Annotated[TicketAccess, Depends(get_delete_access)]


def create_helpdesk_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["Helpdesk"])

    @router.get("/tickets", summary="Переглянути звернення", responses=refusals(401, 403))
    async def list_tickets(
        access: ReadAccess,
        service: HelpdeskServiceDep,
        params: ListParams,
    ) -> Envelope[Page[TicketOut]]:
        items, total = await service.list_tickets(access, params)
        return Envelope(
            data=Page(items=items, page=params.page, page_size=params.page_size, total=total)
        )

    @router.post(
        "/tickets",
        status_code=status.HTTP_201_CREATED,
        summary="Створити звернення",
        # The published description is Ukrainian and has to match the sibling
        # backend character for character, so the lone Cyrillic vowel that
        # looks like a Latin one stays exactly as it is.
        description="Звернення завжди відкривається у статусі NEW під згенерованим номером.",  # noqa: RUF001,
        responses=refusals(401, 403, 404, 409),
    )
    async def create_ticket(
        payload: CreateTicketRequest,
        access: WriteAccess,
        service: HelpdeskServiceDep,
    ) -> Envelope[TicketOut]:
        return Envelope(data=await service.create(access, payload))

    @router.get("/tickets/{id}", summary="Отримати звернення", responses=refusals(401, 403, 404))
    async def get_ticket(
        id: uuid.UUID,  # noqa: A002
        access: ReadAccess,
        service: HelpdeskServiceDep,
    ) -> Envelope[TicketOut]:
        return Envelope(data=await service.get_by_id(access, id))

    @router.patch(
        "/tickets/{id}",
        summary="Оновити звернення без зміни статусу",
        responses=refusals(401, 403, 404, 409),
    )
    async def update_ticket(
        id: uuid.UUID,  # noqa: A002
        payload: UpdateTicketRequest,
        access: WriteAccess,
        service: HelpdeskServiceDep,
    ) -> Envelope[TicketOut]:
        return Envelope(data=await service.update(access, id, payload))

    @router.post(
        "/tickets/{id}/transitions",
        tags=["Helpdesk transitions"],
        summary="Перевести звернення в інший статус",
        description="Дозволені переходи: NEW → OPEN/CLOSED, OPEN → PENDING/RESOLVED/CLOSED, "
        "PENDING → OPEN/RESOLVED/CLOSED, RESOLVED → CLOSED/OPEN. Перехід поза таблицею — "
        "422 `TICKET_TRANSITION_NOT_ALLOWED`.",
        responses=refusals(401, 403, 404, 409, 422),
    )
    async def transition_ticket(
        id: uuid.UUID,  # noqa: A002
        payload: TransitionTicketRequest,
        access: WriteAccess,
        service: HelpdeskServiceDep,
    ) -> Envelope[TicketOut]:
        return Envelope(data=await service.transition(access, id, payload))

    @router.delete(
        "/tickets/{id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        summary="Видалити звернення",
        responses=refusals(401, 403, 404, 409),
    )
    async def delete_ticket(
        id: uuid.UUID,  # noqa: A002
        version: TicketVersion,
        access: DeleteAccess,
        service: HelpdeskServiceDep,
    ) -> Response:
        await service.delete(access, id, version)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
