"""Vocabulary of the helpdesk module."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from app.db.enums import PermissionScope

__all__ = [
    "MAX_BODY_LENGTH",
    "MAX_NOTE_LENGTH",
    "MAX_SEARCH_LENGTH",
    "MAX_SUBJECT_LENGTH",
    "TICKET_ASSIGNEE_NOT_FOUND",
    "TICKET_CONCURRENT_MODIFICATION",
    "TICKET_CONTACT_NOT_FOUND",
    "TICKET_CREATED",
    "TICKET_DELETED",
    "TICKET_DUPLICATE_NUMBER",
    "TICKET_ENTITY_TYPE",
    "TICKET_NOT_FOUND",
    "TICKET_STATUS_TRANSITIONED",
    "TICKET_TRANSITION_NOT_ALLOWED",
    "TICKET_UPDATED",
    "TicketAccess",
    "TicketSortField",
]

#: Machine codes shared between the service and its tests, so a rename cannot
#: pass unnoticed on one side. Each constant is spelled exactly as its value:
#: the string is what a client branches on, and a name that drifted from it
#: would make the grep that checks the two backends agree come up empty.
TICKET_NOT_FOUND = "TICKET_NOT_FOUND"
TICKET_DUPLICATE_NUMBER = "TICKET_DUPLICATE_NUMBER"
TICKET_TRANSITION_NOT_ALLOWED = "TICKET_TRANSITION_NOT_ALLOWED"
#: Optimistic locking is reported per resource, so a client can tell which of
#: several records in one workflow it has to re-read.
TICKET_CONCURRENT_MODIFICATION = "TICKET_CONCURRENT_MODIFICATION"
TICKET_CONTACT_NOT_FOUND = "TICKET_CONTACT_NOT_FOUND"
TICKET_ASSIGNEE_NOT_FOUND = "TICKET_ASSIGNEE_NOT_FOUND"

#: Audit actions and domain event types — deliberately the same strings, so one
#: change is described by one name wherever it is read back.
TICKET_CREATED = "ticket.created"
TICKET_UPDATED = "ticket.updated"
TICKET_STATUS_TRANSITIONED = "ticket.status_transitioned"
TICKET_DELETED = "ticket.deleted"

#: Entity type carried by both the audit trail and the event stream.
TICKET_ENTITY_TYPE = "ticket"

MAX_SUBJECT_LENGTH = 200
MAX_BODY_LENGTH = 5000
MAX_NOTE_LENGTH = 500
MAX_SEARCH_LENGTH = 160

#: Sortable columns, named as the client spells them.
TicketSortField = Literal[
    "createdAt",
    "updatedAt",
    "openedAt",
    "priority",
    "status",
]


@dataclass(frozen=True, slots=True)
class TicketAccess:
    """Who is acting on a ticket, and how broad their grant is.

    The scope travels with the actor rather than being resolved inside the
    service: only the caller knows which permission was checked, and only the
    service knows how to narrow a query with it.
    """

    actor_id: uuid.UUID
    scope: PermissionScope
    ip_address: str | None = None

    @property
    def owned_only(self) -> bool:
        """Whether this actor may see and touch nothing but their own tickets."""
        return self.scope is PermissionScope.OWN
