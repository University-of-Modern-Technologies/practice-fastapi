"""The ticket status machine, exercised without a database.

Every rule about which status may follow which is a pure function over plain
values, so the table below is asserted directly rather than through six HTTP
round trips.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.errors import AppError
from app.db.enums import TicketStatus
from app.modules.helpdesk.transition import (
    ALLOWED_TICKET_STATUS_TRANSITIONS,
    INITIAL_TICKET_STATUS,
    assert_ticket_status_transition,
    can_transition_ticket_status,
    is_terminal_ticket_status,
    resolved_at_update,
)
from app.modules.helpdesk.types import TICKET_TRANSITION_NOT_ALLOWED

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)

#: The published lifecycle, written out again on purpose: a test that derived
#: the table from the module would pass no matter what the module said.
PUBLISHED_TRANSITIONS = {
    TicketStatus.NEW: (TicketStatus.OPEN, TicketStatus.CLOSED),
    TicketStatus.OPEN: (TicketStatus.PENDING, TicketStatus.RESOLVED, TicketStatus.CLOSED),
    TicketStatus.PENDING: (TicketStatus.OPEN, TicketStatus.RESOLVED, TicketStatus.CLOSED),
    TicketStatus.RESOLVED: (TicketStatus.CLOSED, TicketStatus.OPEN),
    TicketStatus.CLOSED: (),
}


def test_the_machine_matches_the_published_table() -> None:
    assert dict(ALLOWED_TICKET_STATUS_TRANSITIONS) == PUBLISHED_TRANSITIONS


def test_every_status_has_an_entry() -> None:
    # A status missing from the table would raise a KeyError deep inside a
    # request rather than be refused as a move.
    assert set(ALLOWED_TICKET_STATUS_TRANSITIONS) == set(TicketStatus)


def test_a_ticket_starts_at_the_beginning_of_the_lifecycle() -> None:
    assert INITIAL_TICKET_STATUS is TicketStatus.NEW


def test_closed_is_the_only_terminal_status() -> None:
    terminal = [status for status in TicketStatus if is_terminal_ticket_status(status)]
    assert terminal == [TicketStatus.CLOSED]
    assert ALLOWED_TICKET_STATUS_TRANSITIONS[TicketStatus.CLOSED] == ()


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (TicketStatus.NEW, TicketStatus.RESOLVED),
        (TicketStatus.NEW, TicketStatus.PENDING),
        (TicketStatus.OPEN, TicketStatus.NEW),
        (TicketStatus.CLOSED, TicketStatus.OPEN),
        (TicketStatus.CLOSED, TicketStatus.CLOSED),
    ],
)
def test_a_move_outside_the_table_is_refused(
    from_status: TicketStatus, to_status: TicketStatus
) -> None:
    assert not can_transition_ticket_status(from_status, to_status)

    with pytest.raises(AppError) as error:
        assert_ticket_status_transition(from_status, to_status)

    assert error.value.status_code == 422
    assert error.value.code == TICKET_TRANSITION_NOT_ALLOWED
    assert error.value.details["from"] == str(from_status)
    assert error.value.details["to"] == str(to_status)


def test_a_refusal_names_the_moves_that_were_available() -> None:
    with pytest.raises(AppError) as error:
        assert_ticket_status_transition(TicketStatus.NEW, TicketStatus.RESOLVED)

    assert error.value.details["allowed"] == ["OPEN", "CLOSED"]


def test_a_permitted_move_passes_silently() -> None:
    for from_status, targets in PUBLISHED_TRANSITIONS.items():
        for to_status in targets:
            assert can_transition_ticket_status(from_status, to_status)
            assert_ticket_status_transition(from_status, to_status)


def test_resolving_a_ticket_stamps_the_moment() -> None:
    assert resolved_at_update(TicketStatus.RESOLVED, NOW) == {"resolved_at": NOW}


@pytest.mark.parametrize("status", [TicketStatus.NEW, TicketStatus.OPEN, TicketStatus.PENDING])
def test_going_back_into_work_clears_the_moment(status: TicketStatus) -> None:
    # A stale resolution on a reopened ticket would misreport how long the
    # customer waited.
    assert resolved_at_update(status, NOW) == {"resolved_at": None}


def test_closing_a_ticket_leaves_the_moment_exactly_as_it_was() -> None:
    # An empty fragment is how "do not touch the column" is spelled: a ticket
    # closed without ever being answered has no resolution time, and one that
    # was answered first keeps the time it had. Erasing it here would take the
    # time-to-resolution report with it.
    assert resolved_at_update(TicketStatus.CLOSED, NOW) == {}


def test_a_resolution_moment_defaults_to_now() -> None:
    stamped = resolved_at_update(TicketStatus.RESOLVED)["resolved_at"]

    assert stamped is not None
    assert stamped.tzinfo is not None
