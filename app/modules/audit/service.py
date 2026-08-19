"""The audit trail.

Two responsibilities that look unrelated but belong together: writing an entry
as part of somebody else's transaction, and reading the trail back.

The write is the interesting one. It runs on the session the calling domain
service already holds, so the business change and its audit entry commit or roll
back as one. An audit trail that can disagree with the data it describes is
worse than none at all, because it is trusted.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.filters import FilterBuilder
from app.core.paged_query import PagedQuery
from app.db.enums import PermissionScope
from app.db.models.audit import AuditLog
from app.modules.audit.sanitize import sanitize_audit_value
from app.modules.audit.schemas import AuditRecordOut
from app.modules.audit.types import AUDIT_RECORD_NOT_FOUND, AuditEvent


@dataclass(frozen=True, slots=True)
class AuditListQuery:
    """Filters accepted when browsing the trail."""

    page: int
    page_size: int
    actor_id: uuid.UUID | None = None
    action: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


def _to_out(entry: AuditLog) -> AuditRecordOut:
    return AuditRecordOut(
        id=entry.id,
        actor_id=entry.actor_id,
        action=entry.action,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        changes=entry.changes,
        metadata=entry.meta,
        ip_address=entry.ip_address,
        created_at=entry.created_at,
    )


class _AuditPage(PagedQuery[AuditLog, AuditListQuery, AuditRecordOut]):
    """One page of the trail, scoped to what one caller may browse."""

    def __init__(self, session: AsyncSession, actor_id: uuid.UUID, scope: PermissionScope) -> None:
        super().__init__(session)
        self._actor_id = actor_id
        self._scope = scope

    def _model(self) -> type[AuditLog]:
        return AuditLog

    def _build_filters(self, params: AuditListQuery) -> list[ColumnElement[bool]]:
        builder = FilterBuilder()
        if self._scope is PermissionScope.OWN:
            # The narrower grant sees only its own actions, and the requested
            # actor filter cannot widen that.
            builder.equals(AuditLog.actor_id, self._actor_id)
        else:
            builder.equals(AuditLog.actor_id, params.actor_id)
        return (
            builder.text(AuditLog.action, params.action)
            .text(AuditLog.entity_type, params.entity_type)
            .equals(AuditLog.entity_id, params.entity_id)
            .range(AuditLog.created_at, params.created_from, params.created_to)
            .build()
        )

    def _order_by(self, _params: AuditListQuery) -> tuple[ColumnElement[Any], ...]:
        # Ordered by id as well as time: two entries written in the same
        # millisecond would otherwise page unpredictably.
        return (AuditLog.created_at.desc(), AuditLog.id.desc())

    def _to_dto(self, row: AuditLog) -> AuditRecordOut:
        return _to_out(row)


class AuditService:
    """Writes and reads audit entries on one session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, event: AuditEvent) -> AuditRecordOut:
        """Appends an entry to the caller's open transaction.

        The row is flushed rather than committed: the caller decides when the
        whole operation becomes visible, and until then the entry can still be
        rolled back with the change it describes.
        """
        entry = AuditLog(
            actor_id=event.actor_id,
            action=event.action,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            changes=sanitize_audit_value(event.changes) if event.changes is not None else None,
            meta=sanitize_audit_value(event.metadata) if event.metadata is not None else None,
            ip_address=event.ip_address,
        )
        self._session.add(entry)
        await self._session.flush()
        return _to_out(entry)

    async def list(
        self, actor_id: uuid.UUID, scope: PermissionScope, query: AuditListQuery
    ) -> tuple[Sequence[AuditRecordOut], int]:
        return await _AuditPage(self._session, actor_id, scope).run(query)

    async def history(
        self,
        actor_id: uuid.UUID,
        scope: PermissionScope,
        resource: str,
        resource_id: uuid.UUID,
        query: AuditListQuery,
    ) -> tuple[Sequence[AuditRecordOut], int]:
        """The trail of one record — the same query, pinned to one entity."""
        return await self.list(
            actor_id,
            scope,
            AuditListQuery(
                page=query.page,
                page_size=query.page_size,
                action=query.action,
                created_from=query.created_from,
                created_to=query.created_to,
                entity_type=resource,
                entity_id=resource_id,
            ),
        )

    async def get_by_id(
        self, actor_id: uuid.UUID, scope: PermissionScope, record_id: uuid.UUID
    ) -> AuditRecordOut:
        statement = select(AuditLog).where(AuditLog.id == record_id)
        if scope is PermissionScope.OWN:
            statement = statement.where(AuditLog.actor_id == actor_id)

        entry = (await self._session.execute(statement)).scalar_one_or_none()
        if entry is None:
            # A record that exists but belongs to somebody else is reported as
            # missing: a narrower scope must not become a way to probe for ids.
            raise NotFoundError("Audit record not found", AUDIT_RECORD_NOT_FOUND)
        return _to_out(entry)
