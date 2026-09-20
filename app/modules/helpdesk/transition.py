"""The ticket status machine.

Every rule about *which* status may follow *which* lives here, as plain
functions over plain values: no session, no request, nothing to mock. That is
deliberate — the lifecycle is the part of this module a mistake would be most
expensive in, so it has to be testable without a database.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from app.core.errors import AppError
from app.db.enums import TicketStatus
from app.modules.helpdesk.types import TICKET_TRANSITION_NOT_ALLOWED

__all__ = [
    "ALLOWED_TICKET_STATUS_TRANSITIONS",
    "INITIAL_TICKET_STATUS",
    "TERMINAL_TICKET_STATUSES",
    "TRANSITION_NOT_ALLOWED_STATUS",
    "assert_ticket_status_transition",
    "can_transition_ticket_status",
    "is_terminal_ticket_status",
    "resolved_at_update",
]

#: The lifecycle. A status absent from a target list is unreachable from that
#: source, which is what makes ``CLOSED`` final: its list is empty, so a closed
#: ticket is never reopened but replaced by a new one.
ALLOWED_TICKET_STATUS_TRANSITIONS: Mapping[TicketStatus, tuple[TicketStatus, ...]] = {
    TicketStatus.NEW: (TicketStatus.OPEN, TicketStatus.CLOSED),
    TicketStatus.OPEN: (TicketStatus.PENDING, TicketStatus.RESOLVED, TicketStatus.CLOSED),
    TicketStatus.PENDING: (TicketStatus.OPEN, TicketStatus.RESOLVED, TicketStatus.CLOSED),
    TicketStatus.RESOLVED: (TicketStatus.CLOSED, TicketStatus.OPEN),
    TicketStatus.CLOSED: (),
}

#: Where a ticket always begins; the machine has no other entry point.
INITIAL_TICKET_STATUS = TicketStatus.NEW

#: Statuses a ticket never leaves; the one with an empty target list above.
TERMINAL_TICKET_STATUSES = (TicketStatus.CLOSED,)

#: A refused move is reported as unprocessable rather than as a conflict: the
#: published contract names this status for the whole lifecycle family, and the
#: two backends have to answer the same number.
TRANSITION_NOT_ALLOWED_STATUS = 422


def is_terminal_ticket_status(status: TicketStatus) -> bool:
    """Whether the lifecycle ends at this status."""
    return status in TERMINAL_TICKET_STATUSES


def can_transition_ticket_status(from_status: TicketStatus, to_status: TicketStatus) -> bool:
    """Whether the machine permits this move."""
    return to_status in ALLOWED_TICKET_STATUS_TRANSITIONS[from_status]


def assert_ticket_status_transition(from_status: TicketStatus, to_status: TicketStatus) -> None:
    """Rejects a move the lifecycle does not allow.

    The details carry the moves that *were* available, so a client that lost a
    race learns the current shape of the machine from the refusal itself
    instead of having to re-read the record and guess.
    """
    if can_transition_ticket_status(from_status, to_status):
        return
    raise AppError(
        f"Ticket cannot transition from {from_status} to {to_status}",
        TRANSITION_NOT_ALLOWED_STATUS,
        TICKET_TRANSITION_NOT_ALLOWED,
        {
            "from": str(from_status),
            "to": str(to_status),
            "allowed": [str(status) for status in ALLOWED_TICKET_STATUS_TRANSITIONS[from_status]],
        },
    )


def resolved_at_update(
    status: TicketStatus, moment: datetime | None = None
) -> dict[str, datetime | None]:
    """What happens to ``resolved_at`` when a ticket enters ``status``.

    Three outcomes, not two — which is why this returns the fragment of an
    update rather than a value. There is no timestamp that means "leave the
    column alone", so the only way to express that is to omit the column, and
    an empty mapping is what omission looks like.

    ``RESOLVED`` stamps the moment. Going back into work — ``NEW``, ``OPEN``,
    ``PENDING`` — clears it, because a stale value on a reopened ticket would
    misreport how long the customer waited. ``CLOSED`` touches nothing: a
    ticket can be closed without ever being answered, and one that *was*
    answered keeps the moment it was. Erasing that on close would take the
    time-to-resolution report with it, by removing exactly the records that
    reached the end.

    The same three cases are enforced by ``tickets_resolved_at_consistency``
    in the database; this is where they are decided.
    """
    if status is TicketStatus.RESOLVED:
        return {"resolved_at": moment if moment is not None else datetime.now(tz=UTC)}
    if status is TicketStatus.CLOSED:
        return {}
    return {"resolved_at": None}
