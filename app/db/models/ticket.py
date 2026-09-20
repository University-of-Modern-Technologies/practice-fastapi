"""Support requests and the trail of their state changes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import TicketChannel, TicketPriority, TicketStatus, pg_enum
from app.db.types import CreatedAt, DeletedAt, LongText, UpdatedAt, UuidFk, UuidPk, Version

if TYPE_CHECKING:
    from app.db.models.contact import Contact
    from app.db.models.user import User

#: An open ticket has no resolution time and a resolved one always has it.
#: Closed is deliberately unconstrained: a ticket can be closed without ever
#: being answered, and one that was answered first keeps the moment it was —
#: erasing that on close would take the time-to-resolution report with it.
RESOLVED_CONSISTENCY_RULE = (
    "(status = 'RESOLVED' AND resolved_at IS NOT NULL) OR "
    "(status IN ('NEW', 'OPEN', 'PENDING') AND resolved_at IS NULL) OR "
    "status = 'CLOSED'"
)


class Ticket(Base):
    """A customer request working its way towards RESOLVED."""

    __tablename__ = "tickets"

    id: Mapped[UuidPk]
    number: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[TicketChannel] = mapped_column(
        pg_enum(TicketChannel, "TicketChannel"), nullable=False
    )
    status: Mapped[TicketStatus] = mapped_column(
        pg_enum(TicketStatus, "TicketStatus"),
        nullable=False,
        default=TicketStatus.NEW,
        server_default=text("'NEW'"),
    )
    priority: Mapped[TicketPriority] = mapped_column(
        pg_enum(TicketPriority, "TicketPriority"),
        nullable=False,
        default=TicketPriority.NORMAL,
        server_default=text("'NORMAL'"),
    )
    owner_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[Version]
    opened_at: Mapped[CreatedAt]
    resolved_at: Mapped[datetime | None]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
    deleted_at: Mapped[DeletedAt]

    owner: Mapped[User] = relationship(
        back_populates="tickets", foreign_keys=[owner_id], lazy="raise"
    )
    assignee: Mapped[User | None] = relationship(
        back_populates="tickets_assigned", foreign_keys=[assignee_id], lazy="raise"
    )
    contact: Mapped[Contact | None] = relationship(back_populates="tickets", lazy="raise")
    status_logs: Mapped[list[TicketStatusLog]] = relationship(
        back_populates="ticket", lazy="raise"
    )

    __table_args__ = (
        Index(None, "owner_id", "status", "deleted_at"),
        Index(None, "status", "priority"),
        Index(None, "contact_id"),
        Index(None, "assignee_id"),
        Index(None, "deleted_at"),
        CheckConstraint("btrim(subject) <> ''", name="subject_nonempty"),
        CheckConstraint("btrim(number) <> ''", name="number_nonempty"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(RESOLVED_CONSISTENCY_RULE, name="resolved_at_consistency"),
        CheckConstraint("resolved_at IS NULL OR resolved_at >= opened_at", name="resolved_at"),
        CheckConstraint("deleted_at IS NULL OR deleted_at >= created_at", name="deleted_at"),
    )


class TicketStatusLog(Base):
    """One recorded move of a ticket from one state to another."""

    __tablename__ = "ticket_status_logs"

    id: Mapped[UuidPk]
    ticket_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[TicketStatus | None] = mapped_column(
        pg_enum(TicketStatus, "TicketStatus"), nullable=True
    )
    to_status: Mapped[TicketStatus] = mapped_column(
        pg_enum(TicketStatus, "TicketStatus"), nullable=False
    )
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[LongText] = mapped_column(String(500), nullable=True)
    changed_at: Mapped[CreatedAt]

    ticket: Mapped[Ticket] = relationship(back_populates="status_logs", lazy="raise")
    changed_by: Mapped[User | None] = relationship(
        back_populates="ticket_status_changes", lazy="raise"
    )

    __table_args__ = (
        Index(None, "ticket_id", "changed_at"),
        CheckConstraint("from_status IS NULL OR from_status <> to_status", name="status_changed"),
    )
