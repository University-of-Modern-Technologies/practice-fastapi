"""Sales opportunities."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import DealStage, pg_enum
from app.db.types import CreatedAt, DeletedAt, Money, UpdatedAt, UuidFk, UuidPk, Version

if TYPE_CHECKING:
    from app.db.models.call import Call
    from app.db.models.contact import Contact
    from app.db.models.order import Order
    from app.db.models.user import User

#: A closed deal has a certain outcome, so its probability is pinned by stage.
STAGE_PROBABILITY_RULE = (
    "(stage = 'WON' AND probability = 100) OR "
    "(stage = 'LOST' AND probability = 0) OR "
    "(stage NOT IN ('WON', 'LOST') AND probability < 100)"
)


class Deal(Base):
    """A deal moving through the pipeline towards WON or LOST."""

    __tablename__ = "deals"

    id: Mapped[UuidPk]
    owner_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    stage: Mapped[DealStage] = mapped_column(
        pg_enum(DealStage, "DealStage"),
        nullable=False,
        default=DealStage.LEAD,
        server_default=text("'LEAD'"),
    )
    amount: Mapped[Money] = mapped_column(default=Decimal("0"), server_default=text("0"))
    currency: Mapped[str] = mapped_column(
        CHAR(3), nullable=False, default="USD", server_default=text("'USD'")
    )
    probability: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default=text("10")
    )
    version: Mapped[Version]
    expected_close_date: Mapped[date | None]
    closed_at: Mapped[datetime | None]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
    deleted_at: Mapped[DeletedAt]

    owner: Mapped[User] = relationship(back_populates="deals", lazy="raise")
    contact: Mapped[Contact | None] = relationship(back_populates="deals", lazy="raise")
    orders: Mapped[list[Order]] = relationship(back_populates="deal", lazy="raise")
    calls: Mapped[list[Call]] = relationship(back_populates="deal", lazy="raise")

    __table_args__ = (
        Index(None, "owner_id", "stage", "deleted_at"),
        Index(None, "contact_id"),
        Index(None, "stage", "expected_close_date"),
        Index(None, "deleted_at"),
        CheckConstraint("btrim(title) <> ''", name="title_nonempty"),
        CheckConstraint("amount >= 0", name="amount_nonnegative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("probability BETWEEN 0 AND 100", name="probability_range"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(STAGE_PROBABILITY_RULE, name="stage_probability"),
        CheckConstraint("closed_at IS NULL OR closed_at >= created_at", name="closed_at"),
        CheckConstraint("deleted_at IS NULL OR deleted_at >= created_at", name="deleted_at"),
    )
