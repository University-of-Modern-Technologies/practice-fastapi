"""Audit trail: what happened, who did it, and what changed.

Domain modules depend on `AuditService` and record their changes on the session
they are already using, which is what keeps a business change and its trail
entry in one transaction.
"""

from __future__ import annotations

from app.modules.audit.router import AuditServiceDep, create_audit_router, get_audit_service
from app.modules.audit.sanitize import is_sensitive_audit_field, sanitize_audit_value
from app.modules.audit.schemas import AuditRecordOut
from app.modules.audit.service import AuditListQuery, AuditService
from app.modules.audit.types import AUDIT_RECORD_NOT_FOUND, AuditEvent

__all__ = [
    "AUDIT_RECORD_NOT_FOUND",
    "AuditEvent",
    "AuditListQuery",
    "AuditRecordOut",
    "AuditService",
    "AuditServiceDep",
    "create_audit_router",
    "get_audit_service",
    "is_sensitive_audit_field",
    "sanitize_audit_value",
]
