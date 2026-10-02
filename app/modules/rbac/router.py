"""HTTP surface of authorization.

Role administration is guarded by the ``users`` permissions rather than by a
permission of its own: whoever may create and edit accounts is exactly whoever
may decide what those accounts can do.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.core.openapi import refusals
from app.core.responses import Envelope
from app.modules.auth.dependencies import CurrentAuth
from app.modules.rbac.dependencies import RbacServiceDep, ensure_scope_all, require_permission
from app.modules.rbac.schemas import (
    CreateRoleRequest,
    PermissionCheckOut,
    ReplaceRolePermissionsRequest,
    RoleOut,
)
from app.modules.rbac.types import PermissionScope

PermissionPartPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
]

ReadScope = Annotated[PermissionScope, Depends(require_permission("users", "read"))]
CreateScope = Annotated[PermissionScope, Depends(require_permission("users", "create"))]
UpdateScope = Annotated[PermissionScope, Depends(require_permission("users", "update"))]


def create_rbac_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["RBAC"])

    @router.get(
        "/check/{resource}/{action}",
        summary="Перевірити дозвіл поточного користувача",
        responses=refusals(401),
    )
    async def check(
        auth: CurrentAuth,
        rbac: RbacServiceDep,
        resource: PermissionPartPath,
        action: PermissionPartPath,
    ) -> Envelope[PermissionCheckOut]:
        scope = await rbac.get_permission_scope(auth.user_id, resource, action)
        return Envelope(data=PermissionCheckOut(allowed=scope is not None, scope=scope))

    @router.get("/roles", tags=["Roles"], summary="Переглянути ролі", responses=refusals(401, 403))
    async def list_roles(scope: ReadScope, rbac: RbacServiceDep) -> Envelope[list[RoleOut]]:
        ensure_scope_all(scope)
        return Envelope(data=await rbac.list_roles())

    @router.post(
        "/roles",
        tags=["Roles"],
        status_code=status.HTTP_201_CREATED,
        summary="Створити роль",
        responses=refusals(401, 403, 409),
    )
    async def create_role(
        payload: CreateRoleRequest, scope: CreateScope, rbac: RbacServiceDep
    ) -> Envelope[RoleOut]:
        ensure_scope_all(scope)
        return Envelope(data=await rbac.create_role(payload))

    @router.put(
        "/roles/{id}/permissions",
        tags=["Roles"],
        summary="Замінити дозволи ролі",
        responses=refusals(401, 403, 404),
    )
    async def replace_role_permissions(
        id: uuid.UUID,  # noqa: A002
        payload: ReplaceRolePermissionsRequest,
        scope: UpdateScope,
        rbac: RbacServiceDep,
    ) -> Envelope[RoleOut]:
        ensure_scope_all(scope)
        return Envelope(data=await rbac.replace_role_permissions(id, payload))

    return router
