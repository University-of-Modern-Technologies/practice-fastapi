"""People and companies the organization does business with."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import CreatedAt, DeletedAt, LongText, UpdatedAt, UuidFk, UuidPk

if TYPE_CHECKING:
    from app.db.models.call import Call
    from app.db.models.deal import Deal
    from app.db.models.order import Order
    from app.db.models.ticket import Ticket
    from app.db.models.user import User


class Contact(Base):
    """A CRM contact. Removal is a soft delete so history stays readable."""

    __tablename__ = "contacts"

    id: Mapped[UuidPk]
    owner_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    company: Mapped[str | None] = mapped_column(String(160), nullable=True)
    notes: Mapped[LongText]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
    deleted_at: Mapped[DeletedAt]

    owner: Mapped[User] = relationship(back_populates="contacts", lazy="raise")
    deals: Mapped[list[Deal]] = relationship(back_populates="contact", lazy="raise")
    orders: Mapped[list[Order]] = relationship(back_populates="contact", lazy="raise")
    tickets: Mapped[list[Ticket]] = relationship(back_populates="contact", lazy="raise")
    calls: Mapped[list[Call]] = relationship(back_populates="contact", lazy="raise")

    __table_args__ = (
        Index(None, "owner_id", "deleted_at"),
        Index(None, "last_name", "first_name"),
        Index(None, "email"),
        Index(None, "company"),
        CheckConstraint("btrim(first_name) <> ''", name="first_name_nonempty"),
        CheckConstraint("btrim(last_name) <> ''", name="last_name_nonempty"),
        CheckConstraint("deleted_at IS NULL OR deleted_at >= created_at", name="deleted_at"),
    )
