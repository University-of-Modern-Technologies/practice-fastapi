"""HTTP surface of organization settings.

The path segment is not an identifier the client invented: it has to be a key
the registry declares, so an unknown key is a 400 rather than a 404 — the
resource does not exist and never will, whatever is stored.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response, status

from app.core.openapi import refusals
from app.core.responses import Envelope
from app.db.enums import PermissionScope
from app.modules.auth.dependencies import CurrentAuth, SessionDep
from app.modules.auth.dependencies import SettingsDep as AppSettingsDep
from app.modules.rbac.dependencies import CacheDep, require_permission
from app.modules.settings.schemas import (
    KEY_PATTERN,
    MAX_KEY_LENGTH,
    SettingOut,
    UpsertSettingRequest,
)
from app.modules.settings.service import SettingsService
from app.modules.settings.types import SettingsAccess

RESOURCE = "settings"


def get_settings_service(
    session: SessionDep,
    cache: CacheDep,
    config: AppSettingsDep,
) -> SettingsService:
    return SettingsService(session, cache, config.cache_ttl_seconds)


SettingsServiceDep = Annotated[SettingsService, Depends(get_settings_service)]


def _require_access(action: str) -> Callable[..., Awaitable[SettingsAccess]]:
    """Builds the dependency that admits a caller and describes them."""
    permission = require_permission(RESOURCE, action)

    # The permission is a default rather than an ``Annotated`` member: postponed
    # annotations turn every hint into a string, and a string naming a local
    # closure is not something FastAPI can resolve at import.
    async def dependency(
        request: Request,
        auth: CurrentAuth,
        _scope: PermissionScope = Depends(permission),
    ) -> SettingsAccess:
        # Settings are organization-wide: there is no owner a narrower grant
        # could be narrowed to, so holding the permission is the whole check.
        ip_address = request.client.host if request.client is not None else None
        return SettingsAccess(actor_id=auth.user_id, ip_address=ip_address)

    return dependency


ReadAccess = Annotated[SettingsAccess, Depends(_require_access("read"))]
WriteAccess = Annotated[SettingsAccess, Depends(_require_access("write"))]

SettingKey = Annotated[str, Path(min_length=1, max_length=MAX_KEY_LENGTH, pattern=KEY_PATTERN)]


def create_settings_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["Settings"])

    @router.get(
        "", summary="Переглянути всі налаштування організації", responses=refusals(401, 403)
    )
    async def list_settings(
        _access: ReadAccess, service: SettingsServiceDep
    ) -> Envelope[list[SettingOut]]:
        return Envelope(data=await service.list())

    @router.get("/{key}", summary="Отримати налаштування за ключем", responses=refusals(401, 403))
    async def get_setting(
        key: SettingKey, _access: ReadAccess, service: SettingsServiceDep
    ) -> Envelope[SettingOut]:
        return Envelope(data=await service.get_by_key(key))

    @router.put("/{key}", summary="Записати значення налаштування", responses=refusals(401, 403))
    async def upsert_setting(
        key: SettingKey,
        payload: UpsertSettingRequest,
        access: WriteAccess,
        service: SettingsServiceDep,
    ) -> Envelope[SettingOut]:
        return Envelope(data=await service.upsert(access, key, payload))

    @router.delete(
        "/{key}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        summary="Скинути налаштування до типового значення",
        responses=refusals(401, 403, 404),
    )
    async def reset_setting(
        key: SettingKey, access: WriteAccess, service: SettingsServiceDep
    ) -> Response:
        await service.remove(access, key)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
