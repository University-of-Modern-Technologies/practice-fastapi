"""Helpdesk: customer requests and the machine that moves them to a resolution.

The status is server-owned. It changes through one endpoint, under one set of
rules, recorded both in the audit trail and in the ticket's own status log every
time — which is what makes the lifecycle a fact about the support desk rather
than a field the client happens to set.
"""

from __future__ import annotations

from app.modules.helpdesk.router import (
    HelpdeskServiceDep,
    create_helpdesk_router,
    get_helpdesk_service,
)
from app.modules.helpdesk.schemas import (
    CreateTicketRequest,
    TicketListParams,
    TicketOut,
    TransitionTicketRequest,
    UpdateTicketRequest,
)
from app.modules.helpdesk.service import HelpdeskService, generate_ticket_number, to_ticket_out
from app.modules.helpdesk.transition import (
    ALLOWED_TICKET_STATUS_TRANSITIONS,
    INITIAL_TICKET_STATUS,
    assert_ticket_status_transition,
    can_transition_ticket_status,
    is_terminal_ticket_status,
    resolved_at_update,
)
from app.modules.helpdesk.types import TicketAccess

__all__ = [
    "ALLOWED_TICKET_STATUS_TRANSITIONS",
    "INITIAL_TICKET_STATUS",
    "CreateTicketRequest",
    "HelpdeskService",
    "HelpdeskServiceDep",
    "TicketAccess",
    "TicketListParams",
    "TicketOut",
    "TransitionTicketRequest",
    "UpdateTicketRequest",
    "assert_ticket_status_transition",
    "can_transition_ticket_status",
    "create_helpdesk_router",
    "generate_ticket_number",
    "get_helpdesk_service",
    "is_terminal_ticket_status",
    "resolved_at_update",
    "to_ticket_out",
]
