"""Vocabulary of the deals module."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from app.db.enums import PermissionScope

__all__ = [
    "CONTACT_NOT_FOUND",
    "DEAL_CREATED",
    "DEAL_DELETED",
    "DEAL_ENTITY_TYPE",
    "DEAL_NOT_FOUND",
    "DEAL_STAGE_TRANSITIONED",
    "DEAL_UPDATED",
    "DEFAULT_CURRENCY",
    "INVALID_DEAL_AMOUNT",
    "INVALID_DEAL_PROBABILITY",
    "INVALID_DEAL_STAGE_TRANSITION",
    "INVALID_INITIAL_DEAL_STAGE",
    "MAX_SEARCH_LENGTH",
    "MAX_TITLE_LENGTH",
    "DealAccess",
    "DealSortField",
]

#: Machine codes shared between the service and its tests, so a rename cannot
#: pass unnoticed on one side.
DEAL_NOT_FOUND = "DEAL_NOT_FOUND"
#: Optimistic locking is reported per resource, so a client can tell which of
#: several records in one workflow it has to re-read.
DEAL_CONCURRENT_MODIFICATION = "DEAL_CONCURRENT_MODIFICATION"
CONTACT_NOT_FOUND = "CONTACT_NOT_FOUND"
INVALID_DEAL_AMOUNT = "INVALID_DEAL_AMOUNT"
INVALID_DEAL_PROBABILITY = "INVALID_DEAL_PROBABILITY"
INVALID_DEAL_STAGE_TRANSITION = "INVALID_DEAL_STAGE_TRANSITION"
INVALID_INITIAL_DEAL_STAGE = "INVALID_INITIAL_DEAL_STAGE"

#: Audit actions and domain event types — deliberately the same strings, so one
#: change is described by one name wherever it is read back.
DEAL_CREATED = "deal.created"
DEAL_UPDATED = "deal.updated"
DEAL_STAGE_TRANSITIONED = "deal.stage_transitioned"
DEAL_DELETED = "deal.deleted"

#: Entity type carried by both the audit trail and the event stream.
DEAL_ENTITY_TYPE = "deal"

DEFAULT_CURRENCY = "USD"
MAX_TITLE_LENGTH = 160
MAX_SEARCH_LENGTH = 160

#: Sortable columns, named as the client spells them.
DealSortField = Literal[
    "createdAt",
    "updatedAt",
    "title",
    "amount",
    "probability",
    "expectedCloseDate",
]


@dataclass(frozen=True, slots=True)
class DealAccess:
    """Who is acting on a deal, and how broad their grant is.

    The scope travels with the actor rather than being resolved inside the
    service: only the caller knows which permission was checked, and only the
    service knows how to narrow a query with it.
    """

    actor_id: uuid.UUID
    scope: PermissionScope
    ip_address: str | None = None

    @property
    def owned_only(self) -> bool:
        """Whether this actor may see and touch nothing but their own deals."""
        return self.scope is PermissionScope.OWN
