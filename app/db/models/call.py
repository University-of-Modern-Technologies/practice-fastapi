"""Telephony records arriving from an external provider."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import CallDirection, CallDisposition, pg_enum
from app.db.types import CreatedAt, DeletedAt, LongText, UpdatedAt, UuidPk, Version

if TYPE_CHECKING:
    from app.db.models.contact import Contact
    from app.db.models.deal import Deal
    from app.db.models.user import User


class Call(Base):
    """One telephone call, as the provider reported it.

    Every association is optional on purpose. A call arrives before anybody has
    decided what it belongs to, and often from a number nobody recognises;
    forcing a contact would mean either inventing one or dropping the record.
    """

    __tablename__ = "calls"

    id: Mapped[UuidPk]
    #: The provider's own identifier, and the reason a repeated sync is safe:
    #: it is what makes importing the same call twice a no-op.
    external_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    direction: Mapped[CallDirection] = mapped_column(
        pg_enum(CallDirection, "CallDirection"), nullable=False
    )
    disposition: Mapped[CallDisposition] = mapped_column(
        pg_enum(CallDisposition, "CallDisposition"), nullable=False
    )
    from_number: Mapped[str] = mapped_column(String(32), nullable=False)
    to_number: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    duration_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deals.id", ondelete="SET NULL"), nullable=True
    )
    recording_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[LongText]
    version: Mapped[Version]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
    deleted_at: Mapped[DeletedAt]

    owner: Mapped[User | None] = relationship(back_populates="calls", lazy="raise")
    contact: Mapped[Contact | None] = relationship(back_populates="calls", lazy="raise")
    deal: Mapped[Deal | None] = relationship(back_populates="calls", lazy="raise")

    __table_args__ = (
        Index(None, "started_at"),
        Index(None, "owner_id", "started_at"),
        Index(None, "contact_id"),
        Index(None, "deal_id"),
        Index(None, "direction", "disposition"),
        Index(None, "deleted_at"),
        CheckConstraint("btrim(external_id) <> ''", name="external_id_nonempty"),
        CheckConstraint("btrim(from_number) <> ''", name="from_number_nonempty"),
        CheckConstraint("btrim(to_number) <> ''", name="to_number_nonempty"),
        CheckConstraint("duration_seconds >= 0", name="duration_nonnegative"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("deleted_at IS NULL OR deleted_at >= created_at", name="deleted_at"),
    )
