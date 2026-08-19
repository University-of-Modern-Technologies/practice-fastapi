"""Authorization as a dependency.

``require_permission`` deliberately returns the scope instead of consuming it.
Answering only "allowed or not" would be enough for a single record but not for
a collection: a caller holding ``OWN`` may list, they may just not list
everybody's rows, and only the domain service knows how to express that.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from app.core.errors import ForbiddenError
from app.db.enums import PermissionScope
from app.modules.auth.dependencies import CurrentAuth, SessionDep, SettingsDep
from app.modules.auth.types import AuthContext
from app.modules.rbac.service import RbacService
from app.modules.rbac.types import CachePort, NoopCache


def get_cache(request: Request) -> CachePort:
    """The cache backend if one was wired in, otherwise a cache that stores nothing."""
    cache = getattr(request.app.state, "cache", None)
    if cache is None:
        return NoopCache()
    return cache  # type: ignore[no-any-return]


CacheDep = Annotated[CachePort, Depends(get_cache)]


def get_rbac_service(session: SessionDep, cache: CacheDep, settings: SettingsDep) -> RbacService:
    return RbacService(session, cache, settings.cache_ttl_seconds)


RbacServiceDep = Annotated[RbacService, Depends(get_rbac_service)]


def require_permission(resource: str, action: str) -> Callable[..., Awaitable[PermissionScope]]:
    """Builds a dependency that admits the caller and reports their breadth.

    It fails only when the caller holds the permission at no breadth at all;
    narrowing a result set to owned records is left to the service, which is the
    only layer that can do it correctly.
    """

    async def dependency(auth: CurrentAuth, rbac: RbacServiceDep) -> PermissionScope:
        scope = await rbac.get_permission_scope(auth.user_id, resource, action)
        if scope is None:
            raise ForbiddenError()
        return scope

    return dependency


def ensure_scope_all(scope: PermissionScope) -> None:
    """Rejects a caller whose grant is narrower than the whole collection."""
    if scope != PermissionScope.ALL:
        raise ForbiddenError()


def ensure_scope_covers(scope: PermissionScope, auth: AuthContext, owner_id: UUID) -> None:
    """Rejects a caller who holds ``OWN`` and is addressing somebody else's record."""
    if scope != PermissionScope.ALL and owner_id != auth.user_id:
        raise ForbiddenError()
