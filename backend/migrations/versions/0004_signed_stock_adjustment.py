"""Let a stock adjustment keep its sign.

The movement log then reconciles with the stock levels; every other movement is
still a positive amount. Adjustments written before this revision were stored
without a sign and stay as they are.

Revision ID: 0004_signed_stock_adjustment
Revises: 0003_order_warehouse_matching
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_signed_stock_adjustment"
down_revision: str | None = "0003_order_warehouse_matching"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MOVEMENT_QUANTITY_SIGN = "quantity > 0 OR (type = 'ADJUSTMENT' AND quantity <> 0)"


def upgrade() -> None:
    op.drop_constraint(
        op.f("stock_movements_quantity_positive_check"), "stock_movements", type_="check"
    )
    op.create_check_constraint(
        op.f("stock_movements_quantity_sign_check"), "stock_movements", MOVEMENT_QUANTITY_SIGN
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("stock_movements_quantity_sign_check"), "stock_movements", type_="check"
    )
    op.create_check_constraint(
        op.f("stock_movements_quantity_positive_check"), "stock_movements", "quantity > 0"
    )
