"""Sales orders and their line items."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import OrderStatus, pg_enum
from app.db.types import CreatedAt, DeletedAt, LongText, Money, UpdatedAt, UuidFk, UuidPk, Version

if TYPE_CHECKING:
    from app.db.models.contact import Contact
    from app.db.models.deal import Deal
    from app.db.models.product import Product
    from app.db.models.user import User

TOTALS_NON_NEGATIVE = "subtotal >= 0 AND discount_total >= 0 AND tax_total >= 0 AND total >= 0"


class Order(Base):
    """A sales order; totals are stored rather than recomputed on read."""

    __tablename__ = "orders"

    id: Mapped[UuidPk]
    order_number: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deals.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[OrderStatus] = mapped_column(
        pg_enum(OrderStatus, "OrderStatus"),
        nullable=False,
        default=OrderStatus.DRAFT,
        server_default=text("'DRAFT'"),
    )
    currency: Mapped[str] = mapped_column(
        CHAR(3), nullable=False, default="USD", server_default=text("'USD'")
    )
    subtotal: Mapped[Money] = mapped_column(default=Decimal("0"), server_default=text("0"))
    discount_total: Mapped[Money] = mapped_column(default=Decimal("0"), server_default=text("0"))
    tax_total: Mapped[Money] = mapped_column(default=Decimal("0"), server_default=text("0"))
    total: Mapped[Money] = mapped_column(default=Decimal("0"), server_default=text("0"))
    notes: Mapped[LongText]
    version: Mapped[Version]
    placed_at: Mapped[datetime | None]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
    deleted_at: Mapped[DeletedAt]

    owner: Mapped[User] = relationship(back_populates="orders", lazy="raise")
    contact: Mapped[Contact | None] = relationship(back_populates="orders", lazy="raise")
    deal: Mapped[Deal | None] = relationship(back_populates="orders", lazy="raise")
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("order_number"),
        Index(None, "owner_id", "status", "deleted_at"),
        Index(None, "contact_id"),
        Index(None, "deal_id"),
        Index(None, "status", "placed_at"),
        Index(None, "deleted_at"),
        CheckConstraint(TOTALS_NON_NEGATIVE, name="totals_non_negative"),
        CheckConstraint("version > 0", name="version_positive"),
    )


class OrderItem(Base):
    """One line of an order, with the catalogue values it was placed at."""

    __tablename__ = "order_items"

    id: Mapped[UuidPk]
    order_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    # Snapshots keep a historical order readable after the catalogue changes.
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Money]
    line_total: Mapped[Money]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    order: Mapped[Order] = relationship(back_populates="items", lazy="raise")
    product: Mapped[Product] = relationship(back_populates="order_items", lazy="raise")

    __table_args__ = (
        UniqueConstraint("order_id", "product_id"),
        Index(None, "product_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("line_total >= 0", name="line_total_non_negative"),
    )
