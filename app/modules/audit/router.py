"""HTTP surface of the audit trail.

Read-only by design: there is no endpoint that writes, edits or deletes an
entry. The trail is only worth consulting if nothing can rewrite it, so entries
appear solely as a by-product of the operations that produced them.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.responses import Envelope, Page
from app.db.enums import PermissionScope
from app.modules.audit.schemas import AuditHistoryParams, AuditListParams, AuditRecordOut
from app.modules.audit.service import AuditListQuery, AuditService
from app.modules.auth.dependencies import CurrentAuth, SessionDep
from app.modules.rbac.dependencies import require_permission


def get_audit_service(session: SessionDep) -> AuditService:
    return AuditService(session)


AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
ReadScope = Annotated[PermissionScope, Depends(require_permission("audit", "read"))]
ListParams = Annotated[AuditListParams, Query()]
HistoryParams = Annotated[AuditHistoryParams, Query()]


def create_audit_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["Audit"])

    @router.get("", summary="Переглянути журнал змін")
    async def list_records(
        auth: CurrentAuth,
        scope: ReadScope,
        service: AuditServiceDep,
        params: ListParams,
    ) -> Envelope[Page[AuditRecordOut]]:
        items, total = await service.list(
            auth.user_id,
            scope,
            AuditListQuery(
                page=params.page,
                page_size=params.page_size,
                actor_id=params.actor_id,
                action=params.action,
                entity_type=params.entity_type,
                entity_id=params.entity_id,
                created_from=params.created_from,
                created_to=params.created_to,
            ),
        )
        return Envelope(
            data=Page(items=items, page=params.page, page_size=params.page_size, total=total)
        )

    # Declared before the single-record route so a two-segment path is never
    # mistaken for an identifier.
    @router.get("/{resource}/{resource_id}", summary="Історія одного запису")
    # Two path segments plus the three standard dependencies; there is nothing
    # here to bundle that would not just hide a parameter.
    async def history(  # noqa: PLR0913, PLR0917
        resource: str,
        resource_id: uuid.UUID,
        auth: CurrentAuth,
        scope: ReadScope,
        service: AuditServiceDep,
        params: HistoryParams,
    ) -> Envelope[Page[AuditRecordOut]]:
        items, total = await service.history(
            auth.user_id,
            scope,
            resource,
            resource_id,
            AuditListQuery(
                page=params.page,
                page_size=params.page_size,
                action=params.action,
                created_from=params.created_from,
                created_to=params.created_to,
            ),
        )
        return Envelope(
            data=Page(items=items, page=params.page, page_size=params.page_size, total=total)
        )

    @router.get("/{record_id}", summary="Отримати запис журналу")
    async def get_record(
        record_id: uuid.UUID,
        auth: CurrentAuth,
        scope: ReadScope,
        service: AuditServiceDep,
    ) -> Envelope[AuditRecordOut]:
        return Envelope(data=await service.get_by_id(auth.user_id, scope, record_id))

    return router
