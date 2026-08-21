"""Vocabulary of the audit trail."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

__all__ = [
    "AUDIT_RECORD_NOT_FOUND",
    "DEFAULT_AUDIT_PAGE_SIZE",
    "AuditEvent",
]

#: Machine code shared between the service and its tests.
AUDIT_RECORD_NOT_FOUND = "AUDIT_RECORD_NOT_FOUND"

#: The trail is browsed in larger pages than the domain collections.
DEFAULT_AUDIT_PAGE_SIZE = 25


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One recorded action, as the domain module describes it.

    ``changes`` and ``metadata`` are free-form: they are sanitised on the way in,
    so a caller may hand over whatever describes the change best without having
    to remember which keys are dangerous.
    """

    action: str
    entity_type: str
    entity_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    changes: Any = None
    metadata: Any = None
    ip_address: str | None = None
