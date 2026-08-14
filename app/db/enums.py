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
