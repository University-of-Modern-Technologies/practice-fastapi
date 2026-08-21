"""HTTP surface of user administration.

Each handler receives the breadth of the caller's grant and decides what it
means for that operation: for a collection it narrows the query, for a single
record it constrains which record may be addressed.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.responses import Envelope, Page
from app.db.enums import PermissionScope
from app.modules.auth.dependencies import CurrentAuth, SessionDep
from app.modules.rbac.dependencies import (
    RbacServiceDep,
    ensure_scope_all,
    ensure_scope_covers,
    require_permission,
)
from app.modules.users.schemas import CreateUserRequest, UpdateUserRequest, UserOut, UserSessionOut
from app.modules.users.service import UsersService

ReadScope = Annotated[PermissionScope, Depends(require_permission("users", "read"))]
CreateScope = Annotated[PermissionScope, Depends(require_permission("users", "create"))]
UpdateScope = Annotated[PermissionScope, Depends(require_permission("users", "update"))]
DisableScope = Annotated[PermissionScope, Depends(require_permission("users", "disable"))]

PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, alias="pageSize")]


def get_users_service(session: SessionDep, rbac: RbacServiceDep) -> UsersService:
    return UsersService(session, rbac)


UsersServiceDep = Annotated[UsersService, Depends(get_users_service)]


def create_users_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["Users"])

    @router.get("", summary="Переглянути користувачів")
    async def list_users(
        scope: ReadScope,
        service: UsersServiceDep,
        page: PageNumber = 1,
        page_size: PageSize = DEFAULT_PAGE_SIZE,
    ) -> Envelope[Page[UserOut]]:
        ensure_scope_all(scope)
        items, total = await service.list_users(page, page_size)
        return Envelope(data=Page(items=items, page=page, page_size=page_size, total=total))

    @router.post("", status_code=status.HTTP_201_CREATED, summary="Створити користувача")
    async def create_user(
        payload: CreateUserRequest, scope: CreateScope, service: UsersServiceDep
    ) -> Envelope[UserOut]:
        ensure_scope_all(scope)
        return Envelope(data=await service.create(payload))

    @router.get("/{id}", summary="Отримати користувача")
    async def get_user(
        id: uuid.UUID,  # noqa: A002
        auth: CurrentAuth,
        scope: ReadScope,
        service: UsersServiceDep,
    ) -> Envelope[UserOut]:
        ensure_scope_covers(scope, auth, id)
        return Envelope(data=await service.get_by_id(id))

    @router.patch("/{id}", summary="Оновити користувача")
    async def update_user(
        id: uuid.UUID,  # noqa: A002
        payload: UpdateUserRequest,
        scope: UpdateScope,
        service: UsersServiceDep,
    ) -> Envelope[UserOut]:
        ensure_scope_all(scope)
        return Envelope(data=await service.update(id, payload))

    @router.post("/{id}/disable", summary="Деактивувати користувача")
    async def disable_user(
        id: uuid.UUID,  # noqa: A002
        scope: DisableScope,
        service: UsersServiceDep,
    ) -> Envelope[UserOut]:
        ensure_scope_all(scope)
        return Envelope(data=await service.disable(id))

    @router.get("/{id}/sessions", tags=["Sessions"], summary="Переглянути сесії користувача")
    async def list_user_sessions(
        id: uuid.UUID,  # noqa: A002
        auth: CurrentAuth,
        scope: ReadScope,
        service: UsersServiceDep,
    ) -> Envelope[list[UserSessionOut]]:
        ensure_scope_covers(scope, auth, id)
        return Envelope(data=await service.list_sessions(id))

    @router.delete(
        "/{id}/sessions/{session_id}",
        tags=["Sessions"],
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        summary="Відкликати сесію користувача",
    )
    async def revoke_user_session(
        id: uuid.UUID,  # noqa: A002
        session_id: uuid.UUID,
        auth: CurrentAuth,
        scope: UpdateScope,
        service: UsersServiceDep,
    ) -> Response:
        ensure_scope_covers(scope, auth, id)
        await service.revoke_session(id, session_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
