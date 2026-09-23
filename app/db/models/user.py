"""Accounts and their authentication sessions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import CreatedAt, IpAddress, UpdatedAt, UuidFk, UuidPk

if TYPE_CHECKING:
    from app.db.models.audit import AuditLog
    from app.db.models.call import Call
    from app.db.models.contact import Contact
    from app.db.models.deal import Deal
    from app.db.models.finance import BankStatement, BankTransaction
    from app.db.models.order import Order
    from app.db.models.rbac import UserRole
    from app.db.models.setting import OrganizationSetting
    from app.db.models.ticket import Ticket, TicketStatusLog
    from app.db.models.warehouse import StockMovement


class User(Base):
    """A person who can sign in and own CRM records."""

    __tablename__ = "users"

    id: Mapped[UuidPk]
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", lazy="raise", passive_deletes=True
    )
    user_roles: Mapped[list[UserRole]] = relationship(
        back_populates="user", lazy="raise", passive_deletes=True
    )
    contacts: Mapped[list[Contact]] = relationship(back_populates="owner", lazy="raise")
    deals: Mapped[list[Deal]] = relationship(back_populates="owner", lazy="raise")
    orders: Mapped[list[Order]] = relationship(back_populates="owner", lazy="raise")
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="actor", lazy="raise")
    stock_movements: Mapped[list[StockMovement]] = relationship(
        back_populates="actor", lazy="raise"
    )
    setting_edits: Mapped[list[OrganizationSetting]] = relationship(
        back_populates="updated_by", lazy="raise"
    )
    # Two paths lead from a user to a ticket, so each names its own column:
    # without that SQLAlchemy cannot tell which foreign key it should follow.
    tickets: Mapped[list[Ticket]] = relationship(
        back_populates="owner", foreign_keys="Ticket.owner_id", lazy="raise"
    )
    tickets_assigned: Mapped[list[Ticket]] = relationship(
        back_populates="assignee", foreign_keys="Ticket.assignee_id", lazy="raise"
    )
    ticket_status_changes: Mapped[list[TicketStatusLog]] = relationship(
        back_populates="changed_by", lazy="raise"
    )
    calls: Mapped[list[Call]] = relationship(back_populates="owner", lazy="raise")
    statement_imports: Mapped[list[BankStatement]] = relationship(
        back_populates="imported_by", lazy="raise"
    )
    transaction_matches: Mapped[list[BankTransaction]] = relationship(
        back_populates="matched_by", lazy="raise"
    )

    __table_args__ = (
        UniqueConstraint("email"),
        Index(None, "is_active"),
        CheckConstraint("btrim(email) <> ''", name="email_nonempty"),
        CheckConstraint("btrim(name) <> ''", name="name_nonempty"),
    )


class Session(Base):
    """A refresh-token grant; revoking a row ends one device's access."""

    __tablename__ = "sessions"

    id: Mapped[UuidPk]
    user_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    ip_address: Mapped[IpAddress]
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    user: Mapped[User] = relationship(back_populates="sessions", lazy="raise")

    __table_args__ = (
        UniqueConstraint("token_hash"),
        Index(None, "user_id", "expires_at"),
        Index(None, "expires_at"),
        CheckConstraint("btrim(token_hash) <> ''", name="token_hash_nonempty"),
        CheckConstraint("expires_at > created_at", name="expiry"),
    )
