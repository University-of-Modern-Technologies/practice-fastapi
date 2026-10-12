"""Record the warehouse an order reserved in; one payment per order; sticky unmatch.

Revision ID: 0003_order_warehouse_matching
Revises: 0002_helpdesk_calls_and_finance
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_order_warehouse_matching"
down_revision: str | None = "0002_helpdesk_calls_and_finance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Orders confirmed before this revision reserved stock in the warehouse the
#: `warehouse.defaultCode` setting named at the time, `CENTRAL` when unset.
BACKFILL_ORDER_WAREHOUSE = """
UPDATE orders SET warehouse_id = warehouses.id
FROM warehouses
WHERE warehouses.code = COALESCE(
        (SELECT value #>> '{}' FROM organization_settings WHERE key = 'warehouse.defaultCode'),
        'CENTRAL'
    )
  AND orders.status IN ('CONFIRMED', 'PAID')
"""

#: An order may already be matched by several payments; the earliest match
#: stays and the others go back to the queue for a person to look at.
RELEASE_DUPLICATE_MATCHES = """
UPDATE bank_transactions SET
    match_status = 'UNMATCHED',
    matched_order_id = NULL,
    matched_by_id = NULL,
    matched_at = NULL,
    version = version + 1
WHERE id IN (
    SELECT id FROM (
        SELECT id, row_number() OVER (
            PARTITION BY matched_order_id ORDER BY matched_at, id
        ) AS position
        FROM bank_transactions
        WHERE matched_order_id IS NOT NULL
    ) AS ranked
    WHERE position > 1
)
"""


def upgrade() -> None:
    op.add_column("orders", sa.Column("warehouse_id", sa.Uuid(), nullable=True))
    op.add_column(
        "bank_transactions",
        sa.Column(
            "auto_match_disabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.execute(BACKFILL_ORDER_WAREHOUSE)
    op.execute(RELEASE_DUPLICATE_MATCHES)
    op.drop_index("bank_transactions_matched_order_id_idx", table_name="bank_transactions")
    op.create_unique_constraint(
        op.f("bank_transactions_matched_order_id_key"), "bank_transactions", ["matched_order_id"]
    )
    op.create_index("orders_warehouse_id_idx", "orders", ["warehouse_id"], unique=False)
    op.create_foreign_key(
        op.f("orders_warehouse_id_fkey"),
        "orders",
        "warehouses",
        ["warehouse_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("orders_warehouse_id_fkey"), "orders", type_="foreignkey")
    op.drop_index("orders_warehouse_id_idx", table_name="orders")
    op.drop_constraint(
        op.f("bank_transactions_matched_order_id_key"), "bank_transactions", type_="unique"
    )
    op.create_index(
        "bank_transactions_matched_order_id_idx",
        "bank_transactions",
        ["matched_order_id"],
        unique=False,
    )
    op.drop_column("bank_transactions", "auto_match_disabled")
    op.drop_column("orders", "warehouse_id")
