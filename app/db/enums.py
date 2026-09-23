"""Domain enumerations.

These are ``StrEnum`` members so the very same objects can be used as SQLAlchemy
column types and as Pydantic schema members — one definition, no translation
table between the persistence layer and the wire format, and a member compares
equal to its wire label.
"""

from __future__ import annotations

import enum

from sqlalchemy import Enum as SAEnum


class PermissionScope(enum.StrEnum):
    """Breadth of a permission grant: every record, or only owned ones."""

    ALL = "ALL"
    OWN = "OWN"


class DealStage(enum.StrEnum):
    """Position of a deal in the sales pipeline."""

    LEAD = "LEAD"
    QUALIFIED = "QUALIFIED"
    PROPOSAL = "PROPOSAL"
    WON = "WON"
    LOST = "LOST"


class OrderStatus(enum.StrEnum):
    """Lifecycle of a sales order."""

    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    PAID = "PAID"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class StockMovementType(enum.StrEnum):
    """Reason a stock quantity changed."""

    RECEIPT = "RECEIPT"
    ISSUE = "ISSUE"
    RESERVATION = "RESERVATION"
    RELEASE = "RELEASE"
    ADJUSTMENT = "ADJUSTMENT"


class TicketChannel(enum.StrEnum):
    """How a support request reached the company."""

    EMAIL = "EMAIL"
    PHONE = "PHONE"
    CHAT = "CHAT"
    WEB = "WEB"


class TicketStatus(enum.StrEnum):
    """Lifecycle of a support ticket."""

    NEW = "NEW"
    OPEN = "OPEN"
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class TicketPriority(enum.StrEnum):
    """How urgently a ticket has to be answered."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class CallDirection(enum.StrEnum):
    """Which side placed the call."""

    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class CallDisposition(enum.StrEnum):
    """How a call ended."""

    ANSWERED = "ANSWERED"
    NO_ANSWER = "NO_ANSWER"
    BUSY = "BUSY"
    FAILED = "FAILED"
    VOICEMAIL = "VOICEMAIL"


class TransactionDirection(enum.StrEnum):
    """Whether money entered the account or left it."""

    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class PaymentMatchStatus(enum.StrEnum):
    """How far a bank transaction got towards an order it pays for."""

    UNMATCHED = "UNMATCHED"
    SUGGESTED = "SUGGESTED"
    MATCHED = "MATCHED"
    IGNORED = "IGNORED"


def pg_enum(enum_type: type[enum.Enum], name: str) -> SAEnum:
    """Maps a Python enum onto a native PostgreSQL enum type.

    ``values_callable`` is the load-bearing argument: without it SQLAlchemy
    persists the *member names* rather than the values, which would silently
    diverge from the labels the sibling backend writes.
    """
    return SAEnum(
        enum_type,
        name=name,
        native_enum=True,
        values_callable=lambda members: [member.value for member in members],
    )
