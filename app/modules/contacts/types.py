"""Vocabulary of the contacts module."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass

from app.db.enums import PermissionScope

__all__ = [
    "CONTACT_CHANNEL_REQUIRED",
    "CONTACT_CREATED",
    "CONTACT_DELETED",
    "CONTACT_DUPLICATE",
    "CONTACT_ENTITY_TYPE",
    "CONTACT_NOT_FOUND",
    "CONTACT_UPDATED",
    "ContactAccess",
    "ContactSortField",
]

#: Machine codes shared between the service and its tests, so a rename cannot
#: pass unnoticed on one side.
CONTACT_NOT_FOUND = "CONTACT_NOT_FOUND"
CONTACT_DUPLICATE = "CONTACT_DUPLICATE"
CONTACT_CHANNEL_REQUIRED = "CONTACT_CHANNEL_REQUIRED"

#: Entity and event labels; the realtime topics and the event log key on them.
CONTACT_ENTITY_TYPE = "contact"
CONTACT_CREATED = "contact.created"
CONTACT_UPDATED = "contact.updated"
CONTACT_DELETED = "contact.deleted"


class ContactSortField(enum.StrEnum):
    """Columns a client may order the collection by.

    An enum rather than a free string: ``sortBy`` ends up in an ``ORDER BY``
    clause, and accepting whatever arrives would make that clause caller-written
    SQL. The values are the wire spelling, the service maps them to columns.
    """

    CREATED_AT = "createdAt"
    UPDATED_AT = "updatedAt"
    FIRST_NAME = "firstName"
    LAST_NAME = "lastName"
    COMPANY = "company"


@dataclass(frozen=True, slots=True)
class ContactAccess:
    """Who is asking, how widely they may see, and from where.

    Carried as one value because all three travel together into every service
    method: the scope decides which rows exist for this caller, and the address
    is what the audit entry is stamped with.
    """

    actor_id: uuid.UUID
    scope: PermissionScope
    ip_address: str | None = None

    @property
    def owned_only(self) -> bool:
        """Whether this actor may see and touch nothing but their own contacts."""
        return self.scope is PermissionScope.OWN
