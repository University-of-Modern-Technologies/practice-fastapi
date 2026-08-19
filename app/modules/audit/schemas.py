"""Wire shapes of the audit trail."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.core.pagination import MAX_PAGE_SIZE
from app.core.responses import CamelModel
from app.core.serializers import UtcDatetime
from app.modules.audit.types import DEFAULT_AUDIT_PAGE_SIZE


class AuditHistoryParams(CamelModel):
    """Filters accepted when reading the trail of a single record.

    Grouped into a model rather than spelled out as a dozen handler arguments:
    the same filters are accepted by two endpoints, and FastAPI reads a model
    as query parameters just as happily.
    """

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_AUDIT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    action: str | None = Field(default=None, min_length=1, max_length=64)
    created_from: datetime | None = None
    created_to: datetime | None = None


class AuditListParams(AuditHistoryParams):
    """Filters accepted when browsing the whole trail."""

    actor_id: uuid.UUID | None = None
    entity_type: str | None = Field(default=None, min_length=1, max_length=64)
    entity_id: uuid.UUID | None = None


class AuditRecordOut(CamelModel):
    """One entry as the API publishes it."""

    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    changes: Any = None
    metadata: Any = None
    ip_address: str | None
    created_at: UtcDatetime
