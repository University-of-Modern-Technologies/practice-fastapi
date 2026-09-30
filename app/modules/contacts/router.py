"""HTTP surface of the contact directory.

Every handler receives the breadth of the caller's grant and hands it to the
service untouched. The router deliberately decides nothing about visibility
itself: only the service can express "own records" as part of a query, and a
check split between two layers is a check that eventually disagrees with itself.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.openapi import refusals
from app.core.responses import Envelope, Page
from app.db.enums import PermissionScope
from app.modules.auth.dependencies import CurrentAuth, SessionDep
from app.modules.contacts.schemas import (
    ContactListParams,
    ContactOut,
    CreateContactRequest,
    UpdateContactRequest,
)
from app.modules.contacts.service import ContactsService
from app.modules.contacts.types import ContactAccess
from app.modules.rbac.dependencies import require_permission

ReadScope = Annotated[PermissionScope, Depends(require_permission("contacts", "read"))]
WriteScope = Annotated[PermissionScope, Depends(require_permission("contacts", "write"))]
DeleteScope = Annotated[PermissionScope, Depends(require_permission("contacts", "delete"))]

ListParams = Annotated[ContactListParams, Query()]


def get_contacts_service(session: SessionDep) -> ContactsService:
    return ContactsService(session)


ContactsServiceDep = Annotated[ContactsService, Depends(get_contacts_service)]


def _access(request: Request, auth: CurrentAuth, scope: PermissionScope) -> ContactAccess:
    """Bundles the caller's identity, breadth and address for the service.

    The peer address is read from the connection rather than from a forwarded
    header: the header is caller-controlled, and an audit entry that records
    whatever the client claimed is worse than one that records nothing.
    """
    client = request.client
    return ContactAccess(
        actor_id=auth.user_id,
        scope=scope,
        ip_address=client.host if client else None,
    )


def create_contacts_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["Contacts"])

    @router.get("", summary="Переглянути контакти", responses=refusals(401, 403))
    async def list_contacts(
        request: Request,
        auth: CurrentAuth,
        scope: ReadScope,
        service: ContactsServiceDep,
        params: ListParams,
    ) -> Envelope[Page[ContactOut]]:
        items, total = await service.list(_access(request, auth, scope), params)
        return Envelope(
            data=Page(items=items, page=params.page, page_size=params.page_size, total=total)
        )

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        summary="Створити контакт",
        responses=refusals(401, 403, 409),
    )
    async def create_contact(
        request: Request,
        payload: CreateContactRequest,
        auth: CurrentAuth,
        scope: WriteScope,
        service: ContactsServiceDep,
    ) -> Envelope[ContactOut]:
        return Envelope(data=await service.create(_access(request, auth, scope), payload))

    @router.get("/{id}", summary="Отримати контакт", responses=refusals(401, 403, 404))
    async def get_contact(
        request: Request,
        id: uuid.UUID,  # noqa: A002
        auth: CurrentAuth,
        scope: ReadScope,
        service: ContactsServiceDep,
    ) -> Envelope[ContactOut]:
        return Envelope(data=await service.get_by_id(_access(request, auth, scope), id))

    @router.patch("/{id}", summary="Оновити контакт", responses=refusals(401, 403, 404, 409))
    # A path parameter, a body and the three standard dependencies; there is
    # nothing here to bundle that would not just hide a parameter.
    async def update_contact(  # noqa: PLR0913, PLR0917
        request: Request,
        id: uuid.UUID,  # noqa: A002
        payload: UpdateContactRequest,
        auth: CurrentAuth,
        scope: WriteScope,
        service: ContactsServiceDep,
    ) -> Envelope[ContactOut]:
        return Envelope(data=await service.update(_access(request, auth, scope), id, payload))

    @router.delete(
        "/{id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        summary="Видалити контакт",
        responses=refusals(401, 403, 404),
    )
    async def delete_contact(
        request: Request,
        id: uuid.UUID,  # noqa: A002
        auth: CurrentAuth,
        scope: DeleteScope,
        service: ContactsServiceDep,
    ) -> Response:
        await service.delete(_access(request, auth, scope), id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
