"""HTTP surface of the call log.

Seven endpoints, and only one of them talks to the telephony provider. That
split is deliberate: ``POST /calls/sync`` is where a third party's bad day can
reach us, and it is the only place it can. Browsing the log, linking a call to a
customer and listening back all read what a previous sync already stored, so a
provider that is down costs this module one endpoint rather than all of it.

The provider itself is resolved from the application rather than built per
request: constructing one per call would re-emit the "running on the stub"
warning on every sync and, for the HTTP provider, discard connection reuse.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.responses import Envelope, Page
from app.db.enums import PermissionScope
from app.events.dependencies import PublisherDep
from app.modules.auth.dependencies import CurrentAuth, SessionDep
from app.modules.calls.provider import CallProvider
from app.modules.calls.provider_factory import (
    DEFAULT_CALL_SYNC_BATCH_SIZE,
    CallProviderConfig,
    create_call_provider,
)
from app.modules.calls.schemas import (
    CallListParams,
    CallOut,
    CallRecordingOut,
    LinkCallRequest,
    SyncCallsOut,
    UpdateCallRequest,
)
from app.modules.calls.service import CallsService
from app.modules.calls.types import CallAccess
from app.modules.rbac.dependencies import require_permission

RESOURCE = "calls"

ReadScope = Annotated[PermissionScope, Depends(require_permission(RESOURCE, "read"))]
WriteScope = Annotated[PermissionScope, Depends(require_permission(RESOURCE, "write"))]
DeleteScope = Annotated[PermissionScope, Depends(require_permission(RESOURCE, "delete"))]

ListParams = Annotated[CallListParams, Query()]
CallVersion = Annotated[int, Query(ge=1)]


def get_call_provider_config(request: Request) -> CallProviderConfig:
    """Telephony configuration published by the composition root, if any.

    Absent means "nothing configured", which the factory reads as "use the
    offline stub" — the module answers on a fresh checkout either way.
    """
    config = getattr(request.app.state, "call_provider_config", None)
    return config if isinstance(config, CallProviderConfig) else CallProviderConfig()


CallProviderConfigDep = Annotated[CallProviderConfig, Depends(get_call_provider_config)]


def get_call_provider(request: Request, config: CallProviderConfigDep) -> CallProvider:
    """The provider this application syncs from, built once and remembered."""
    provider = getattr(request.app.state, "call_provider", None)
    if provider is None:
        provider = create_call_provider(config)
        request.app.state.call_provider = provider
    return cast("CallProvider", provider)


CallProviderDep = Annotated[CallProvider, Depends(get_call_provider)]


def get_sync_batch_size(request: Request) -> int:
    """How many records one sync run may take.

    A deployment knob rather than a request parameter: the caller asks for a
    sync, not for a page of one.
    """
    size = getattr(request.app.state, "call_sync_batch_size", None)
    return size if isinstance(size, int) and size > 0 else DEFAULT_CALL_SYNC_BATCH_SIZE


SyncBatchSizeDep = Annotated[int, Depends(get_sync_batch_size)]


def get_calls_service(
    session: SessionDep,
    provider: CallProviderDep,
    publisher: PublisherDep,
    sync_batch_size: SyncBatchSizeDep,
) -> CallsService:
    return CallsService(session, provider, publisher, sync_batch_size=sync_batch_size)


CallsServiceDep = Annotated[CallsService, Depends(get_calls_service)]


def _client_ip(request: Request) -> str | None:
    """The address the audit trail records the change against.

    Read from the connection rather than from a forwarded header: the header is
    caller-controlled, and an audit entry that records whatever the client
    claimed is worse than one that records nothing.
    """
    return request.client.host if request.client is not None else None


def _access(auth: CurrentAuth, request: Request, scope: PermissionScope) -> CallAccess:
    return CallAccess(actor_id=auth.user_id, scope=scope, ip_address=_client_ip(request))


# Identity, breadth of grant and client address are resolved together, so a
# handler takes one argument instead of three and cannot forget one of them.
async def get_read_access(auth: CurrentAuth, request: Request, scope: ReadScope) -> CallAccess:
    return _access(auth, request, scope)


async def get_write_access(auth: CurrentAuth, request: Request, scope: WriteScope) -> CallAccess:
    return _access(auth, request, scope)


async def get_delete_access(auth: CurrentAuth, request: Request, scope: DeleteScope) -> CallAccess:
    return _access(auth, request, scope)


ReadAccess = Annotated[CallAccess, Depends(get_read_access)]
WriteAccess = Annotated[CallAccess, Depends(get_write_access)]
DeleteAccess = Annotated[CallAccess, Depends(get_delete_access)]


def create_calls_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["Calls"])

    @router.get("", summary="Переглянути журнал дзвінків")
    async def list_calls(
        access: ReadAccess,
        service: CallsServiceDep,
        params: ListParams,
    ) -> Envelope[Page[CallOut]]:
        items, total = await service.list_calls(access, params)
        return Envelope(
            data=Page(items=items, page=params.page, page_size=params.page_size, total=total)
        )

    # Declared before `/{id}` so the literal path wins the match outright,
    # rather than depending on `sync` failing to parse as an identifier.
    @router.post(
        "/sync",
        summary="Синхронізувати дзвінки з провайдером",
        description="Повторний виклик не створює дублів: ключ ідемпотентності — `externalId`. "
        "Недоступний провайдер — 502 `CALL_PROVIDER_UNAVAILABLE`.",
    )
    async def sync_calls(
        access: WriteAccess,
        service: CallsServiceDep,
    ) -> Envelope[SyncCallsOut]:
        return Envelope(data=await service.sync(access))

    @router.get("/{id}", summary="Отримати дзвінок")
    async def get_call(
        id: uuid.UUID,  # noqa: A002
        access: ReadAccess,
        service: CallsServiceDep,
    ) -> Envelope[CallOut]:
        return Envelope(data=await service.get_by_id(access, id))

    @router.patch("/{id}", summary="Оновити дзвінок")
    async def update_call(
        id: uuid.UUID,  # noqa: A002
        payload: UpdateCallRequest,
        access: WriteAccess,
        service: CallsServiceDep,
    ) -> Envelope[CallOut]:
        return Envelope(data=await service.update(access, id, payload))

    # The published summary is Ukrainian and has to match the sibling backend
    # character for character, so the lone Cyrillic word whose letters all look
    # Latin stays exactly as it is.
    @router.post("/{id}/link", summary="Прив'язати дзвінок до контакту або угоди")  # noqa: RUF001
    async def link_call(
        id: uuid.UUID,  # noqa: A002
        payload: LinkCallRequest,
        access: WriteAccess,
        service: CallsServiceDep,
    ) -> Envelope[CallOut]:
        return Envelope(data=await service.link(access, id, payload))

    @router.get(
        "/{id}/recording",
        summary="Отримати запис розмови",
        description="Якщо запису немає — 404 `CALL_RECORDING_UNAVAILABLE`.",
    )
    async def get_call_recording(
        id: uuid.UUID,  # noqa: A002
        access: ReadAccess,
        service: CallsServiceDep,
    ) -> Envelope[CallRecordingOut]:
        return Envelope(data=await service.get_recording(access, id))

    @router.delete(
        "/{id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        summary="Видалити дзвінок",
    )
    async def delete_call(
        id: uuid.UUID,  # noqa: A002
        version: CallVersion,
        access: DeleteAccess,
        service: CallsServiceDep,
    ) -> Response:
        await service.delete(access, id, version)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
