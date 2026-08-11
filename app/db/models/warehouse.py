"""Warehouses, current stock and the movements that changed it."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
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
from app.db.enums import StockMovementType, pg_enum
from app.db.types import CreatedAt, UpdatedAt, UuidFk, UuidPk, Version

if TYPE_CHECKING:
    from app.db.models.product import Product
    from app.db.models.user import User

QUANTITIES_NON_NEGATIVE = "quantity_on_hand >= 0 AND quantity_reserved >= 0"


class Warehouse(Base):
    """A physical or logical location that holds stock."""

    __tablename__ = "warehouses"

    id: Mapped[UuidPk]
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    stock: Mapped[list[StockLevel]] = relationship(
        back_populates="warehouse", lazy="raise", passive_deletes=True
    )
    movements: Mapped[list[StockMovement]] = relationship(back_populates="warehouse", lazy="raise")

    __table_args__ = (UniqueConstraint("code"),)


class StockLevel(Base):
    """Current quantities of one product in one warehouse."""

    __tablename__ = "stock_levels"

    id: Mapped[UuidPk]
    warehouse_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    quantity_on_hand: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    quantity_reserved: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    version: Mapped[Version]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    warehouse: Mapped[Warehouse] = relationship(back_populates="stock", lazy="raise")
    product: Mapped[Product] = relationship(back_populates="stock_levels", lazy="raise")

    __table_args__ = (
        UniqueConstraint("warehouse_id", "product_id"),
        Index(None, "product_id"),
        CheckConstraint(QUANTITIES_NON_NEGATIVE, name="quantities_non_negative"),
        CheckConstraint("quantity_reserved <= quantity_on_hand", name="reserved_within_on_hand"),
        CheckConstraint("version > 0", name="version_positive"),
    )


class StockMovement(Base):
    """An append-only record of a stock change; never updated in place."""

    __tablename__ = "stock_movements"

    id: Mapped[UuidPk]
    warehouse_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[StockMovementType] = mapped_column(
        pg_enum(StockMovementType, "StockMovementType"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_id: Mapped[uuid.UUID | None]
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[CreatedAt]

    warehouse: Mapped[Warehouse] = relationship(back_populates="movements", lazy="raise")
    product: Mapped[Product] = relationship(back_populates="movements", lazy="raise")
    actor: Mapped[User | None] = relationship(back_populates="stock_movements", lazy="raise")

    __table_args__ = (
        Index(None, "warehouse_id", "product_id", "created_at"),
        Index(None, "reference_type", "reference_id"),
        Index(None, "type", "created_at"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )
