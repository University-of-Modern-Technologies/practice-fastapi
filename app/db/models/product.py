"""Catalogue of sellable items."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, Boolean, CheckConstraint, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import CreatedAt, DeletedAt, LongText, Money, UpdatedAt, UuidPk, Version

if TYPE_CHECKING:
    from app.db.models.order import OrderItem
    from app.db.models.warehouse import StockLevel, StockMovement


class Product(Base):
    """A catalogue entry. Orders snapshot its price, so edits are safe."""

    __tablename__ = "products"

    id: Mapped[UuidPk]
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[LongText]
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    unit_price: Mapped[Money] = mapped_column(default=Decimal("0"), server_default=text("0"))
    currency: Mapped[str] = mapped_column(
        CHAR(3), nullable=False, default="USD", server_default=text("'USD'")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    version: Mapped[Version]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
    deleted_at: Mapped[DeletedAt]

    order_items: Mapped[list[OrderItem]] = relationship(back_populates="product", lazy="raise")
    stock_levels: Mapped[list[StockLevel]] = relationship(
        back_populates="product", lazy="raise", passive_deletes=True
    )
    movements: Mapped[list[StockMovement]] = relationship(back_populates="product", lazy="raise")

    __table_args__ = (
        UniqueConstraint("sku"),
        Index(None, "category", "is_active"),
        Index(None, "name"),
        Index(None, "deleted_at"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("version > 0", name="version_positive"),
    )
