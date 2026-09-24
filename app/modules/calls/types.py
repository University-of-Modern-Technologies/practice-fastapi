"""Vocabulary of the calls module."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from app.db.enums import PermissionScope

__all__ = [
    "CALL_CONCURRENT_MODIFICATION",
    "CALL_CONTACT_NOT_FOUND",
    "CALL_CREATED",
    "CALL_DEAL_NOT_FOUND",
    "CALL_DELETED",
    "CALL_ENTITY_TYPE",
    "CALL_LINKED",
    "CALL_NOT_FOUND",
    "CALL_PROVIDER_UNAVAILABLE",
    "CALL_RECORDING_UNAVAILABLE",
    "CALL_UPDATED",
    "MAX_EXTERNAL_ID_LENGTH",
    "MAX_NOTES_LENGTH",
    "MAX_NUMBER_LENGTH",
    "MAX_RECORDING_URL_LENGTH",
    "MAX_SEARCH_LENGTH",
    "CallAccess",
    "CallSortField",
]

#: Machine codes shared between the service and its tests, so a rename cannot
#: pass unnoticed on one side. Each constant is spelled exactly as its value:
#: the string is what a client branches on, and a name that drifted from it
#: would make the grep that checks the two backends agree come up empty.
CALL_NOT_FOUND = "CALL_NOT_FOUND"
#: Optimistic locking is reported per resource, so a client can tell which of
#: several records in one workflow it has to re-read.
CALL_CONCURRENT_MODIFICATION = "CALL_CONCURRENT_MODIFICATION"
CALL_CONTACT_NOT_FOUND = "CALL_CONTACT_NOT_FOUND"
CALL_DEAL_NOT_FOUND = "CALL_DEAL_NOT_FOUND"
CALL_RECORDING_UNAVAILABLE = "CALL_RECORDING_UNAVAILABLE"
CALL_PROVIDER_UNAVAILABLE = "CALL_PROVIDER_UNAVAILABLE"

#: Audit actions and domain event types — deliberately the same strings, so one
#: change is described by one name wherever it is read back.
CALL_CREATED = "call.created"
CALL_UPDATED = "call.updated"
CALL_LINKED = "call.linked"
CALL_DELETED = "call.deleted"

#: Entity type carried by both the audit trail and the event stream.
CALL_ENTITY_TYPE = "call"

MAX_EXTERNAL_ID_LENGTH = 64
MAX_NUMBER_LENGTH = 32
MAX_RECORDING_URL_LENGTH = 512
MAX_NOTES_LENGTH = 2000
MAX_SEARCH_LENGTH = 160

#: Sortable columns, named as the client spells them. The default is
#: ``startedAt`` rather than ``createdAt``: a call log is read as a timeline of
#: when people actually spoke, not of when the sync happened to import them.
CallSortField = Literal[
    "startedAt",
    "createdAt",
    "durationSeconds",
]


@dataclass(frozen=True, slots=True)
class CallAccess:
    """Who is acting on a call, and how broad their grant is.

    The scope travels with the actor rather than being resolved inside the
    service: only the caller knows which permission was checked, and only the
    service knows how to narrow a query with it.
    """

    actor_id: uuid.UUID
    scope: PermissionScope
    ip_address: str | None = None

    @property
    def owned_only(self) -> bool:
        """Whether this actor may see and touch nothing but their own calls.

        What "their own" means here is the one decision this module could not
        inherit, because a call is the first record in this system whose owner
        is allowed to be absent. ``owner_id`` is nullable, and a synced call
        arrives owned by nobody until somebody claims it.

        The rule is deliberately the literal one: ``owner_id = :actor``. An
        unowned call is therefore **invisible** to a narrow grant — not shared
        with everybody, not visible to the first caller who asks. SQL settles
        it the same way by itself, since ``NULL = :actor`` is never true, so the
        predicate needs no special case and cannot drift between the two
        backends.

        The alternative — treating "nobody's" as "everybody's" — was rejected
        because it inverts the meaning of the grant: a scope that exists to
        narrow a result set would start widening it, and every freshly imported
        call would be visible to every narrowed account at once, which is
        exactly where the volume is.

        The consequence runs in both directions, and that is deliberate. A
        narrow grant cannot claim an unowned call either: it cannot see the
        record, so it cannot address it. Ownership is handed out from above, by
        a caller who sees the whole log — and a narrow grant may not hand its
        own call on to a colleague, nor release it back to nobody, because both
        put the record beyond its own view. Either attempt is a 403.
        """
        return self.scope is PermissionScope.OWN
