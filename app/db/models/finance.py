"""Bank statements and the transactions reconciled against orders."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import PaymentMatchStatus, TransactionDirection, pg_enum
from app.db.types import CreatedAt, Money, UpdatedAt, UuidFk, UuidPk, Version

if TYPE_CHECKING:
    from app.db.models.order import Order
    from app.db.models.user import User

#: A transaction points at an order exactly when it claims to be matched to
#: one. Without this a row could read MATCHED while naming nothing, which is
#: the state a reconciliation report cannot describe.
MATCH_CONSISTENCY_RULE = (
    "(match_status = 'MATCHED' AND matched_order_id IS NOT NULL) OR "
    "(match_status <> 'MATCHED' AND matched_order_id IS NULL)"
)


class BankStatement(Base):
    """One period of account activity, as the bank issued it."""

    __tablename__ = "bank_statements"

    id: Mapped[UuidPk]
    external_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    account_label: Mapped[str] = mapped_column(String(64), nullable=False)
    period_start: Mapped[date] = mapped_column(nullable=False)
    period_end: Mapped[date] = mapped_column(nullable=False)
    opening_balance: Mapped[Money] = mapped_column(default=Decimal("0"), server_default=text("0"))
    closing_balance: Mapped[Money] = mapped_column(default=Decimal("0"), server_default=text("0"))
    currency: Mapped[str] = mapped_column(
        CHAR(3), nullable=False, default="USD", server_default=text("'USD'")
    )
    imported_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    imported_at: Mapped[CreatedAt]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    imported_by: Mapped[User | None] = relationship(
        back_populates="statement_imports", lazy="raise"
    )
    transactions: Mapped[list[BankTransaction]] = relationship(
        back_populates="statement", lazy="raise"
    )

    __table_args__ = (
        Index(None, "period_start", "period_end"),
        CheckConstraint("btrim(external_id) <> ''", name="external_id_nonempty"),
        CheckConstraint("period_end >= period_start", name="period_ordered"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
    )


class BankTransaction(Base):
    """One line of a statement, and how far it got towards an order."""

    __tablename__ = "bank_transactions"

    id: Mapped[UuidPk]
    statement_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("bank_statements.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    booked_at: Mapped[datetime] = mapped_column(nullable=False)
    amount: Mapped[Money]
    currency: Mapped[str] = mapped_column(
        CHAR(3), nullable=False, default="USD", server_default=text("'USD'")
    )
    direction: Mapped[TransactionDirection] = mapped_column(
        pg_enum(TransactionDirection, "TransactionDirection"), nullable=False
    )
    counterparty_name: Mapped[str] = mapped_column(String(200), nullable=False)
    counterparty_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: What the payer typed. Free text written by somebody outside the company,
    #: which is why reconciliation is a guess and not a lookup.
    reference: Mapped[str] = mapped_column(String(300), nullable=False)
    match_status: Mapped[PaymentMatchStatus] = mapped_column(
        pg_enum(PaymentMatchStatus, "PaymentMatchStatus"),
        nullable=False,
        default=PaymentMatchStatus.UNMATCHED,
        server_default=text("'UNMATCHED'"),
    )
    matched_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    matched_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    matched_at: Mapped[datetime | None]
    version: Mapped[Version]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    statement: Mapped[BankStatement] = relationship(back_populates="transactions", lazy="raise")
    matched_order: Mapped[Order | None] = relationship(
        back_populates="bank_transactions", lazy="raise"
    )
    matched_by: Mapped[User | None] = relationship(
        back_populates="transaction_matches", lazy="raise"
    )

    __table_args__ = (
        Index(None, "statement_id", "booked_at"),
        Index(None, "match_status", "booked_at"),
        Index(None, "matched_order_id"),
        Index(None, "booked_at"),
        CheckConstraint("btrim(external_id) <> ''", name="external_id_nonempty"),
        CheckConstraint("btrim(counterparty_name) <> ''", name="counterparty_nonempty"),
        CheckConstraint("amount >= 0", name="amount_nonnegative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(MATCH_CONSISTENCY_RULE, name="match_consistency"),
    )
