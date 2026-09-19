"""Support tickets, telephony records, bank statements and payment matching.

Revision ID: 0002_helpdesk_calls_and_finance
Revises: 0001_initial
Create Date: 2026-09-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_helpdesk_calls_and_finance"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Native enum types, dropped explicitly on downgrade because dropping a table
#: does not remove the type it referenced.
ENUM_TYPES = (
    "TicketChannel",
    "TicketStatus",
    "TicketPriority",
    "CallDirection",
    "CallDisposition",
    "TransactionDirection",
    "PaymentMatchStatus",
)

#: A ticket is resolved exactly when it carries a resolution time.
RESOLVED_CONSISTENCY_RULE = (
    "(status IN ('RESOLVED', 'CLOSED') AND resolved_at IS NOT NULL) OR "
    "(status NOT IN ('RESOLVED', 'CLOSED') AND resolved_at IS NULL)"
)

#: A transaction names an order exactly when it claims to be matched to one.
MATCH_CONSISTENCY_RULE = (
    "(match_status = 'MATCHED' AND matched_order_id IS NOT NULL) OR "
    "(match_status <> 'MATCHED' AND matched_order_id IS NULL)"
)


def upgrade() -> None:
    op.create_table(
        "bank_statements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("account_label", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "opening_balance",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "closing_balance",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("currency", sa.CHAR(length=3), server_default=sa.text("'USD'"), nullable=False),
        sa.Column("imported_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "imported_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(external_id) <> ''", name="bank_statements_external_id_nonempty_check"
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="bank_statements_currency_format_check"),
        sa.CheckConstraint(
            "period_end >= period_start", name="bank_statements_period_ordered_check"
        ),
        sa.ForeignKeyConstraint(
            ["imported_by_id"],
            ["users.id"],
            name="bank_statements_imported_by_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="bank_statements_pkey"),
        sa.UniqueConstraint("external_id", name="bank_statements_external_id_key"),
    )
    op.create_index(
        "bank_statements_period_start_period_end_idx",
        "bank_statements",
        ["period_start", "period_end"],
        unique=False,
    )
    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "channel",
            sa.Enum("EMAIL", "PHONE", "CHAT", "WEB", name="TicketChannel"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("NEW", "OPEN", "PENDING", "RESOLVED", "CLOSED", name="TicketStatus"),
            server_default=sa.text("'NEW'"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum("LOW", "NORMAL", "HIGH", "URGENT", name="TicketPriority"),
            server_default=sa.text("'NORMAL'"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "opened_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=True),
        sa.CheckConstraint(
            RESOLVED_CONSISTENCY_RULE,
            name="tickets_resolved_at_consistency_check",
        ),
        sa.CheckConstraint("btrim(number) <> ''", name="tickets_number_nonempty_check"),
        sa.CheckConstraint("btrim(subject) <> ''", name="tickets_subject_nonempty_check"),
        sa.CheckConstraint(
            "deleted_at IS NULL OR deleted_at >= created_at", name="tickets_deleted_at_check"
        ),
        sa.CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= opened_at",
            name="tickets_resolved_at_check",
        ),
        sa.CheckConstraint("version > 0", name="tickets_version_positive_check"),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name="tickets_assignee_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name="tickets_contact_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="tickets_owner_id_fkey", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="tickets_pkey"),
        sa.UniqueConstraint("number", name="tickets_number_key"),
    )
    op.create_index("tickets_assignee_id_idx", "tickets", ["assignee_id"], unique=False)
    op.create_index("tickets_contact_id_idx", "tickets", ["contact_id"], unique=False)
    op.create_index("tickets_deleted_at_idx", "tickets", ["deleted_at"], unique=False)
    op.create_index(
        "tickets_owner_id_status_deleted_at_idx",
        "tickets",
        ["owner_id", "status", "deleted_at"],
        unique=False,
    )
    op.create_index("tickets_status_priority_idx", "tickets", ["status", "priority"], unique=False)
    op.create_table(
        "calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column(
            "direction", sa.Enum("INBOUND", "OUTBOUND", name="CallDirection"), nullable=False
        ),
        sa.Column(
            "disposition",
            sa.Enum("ANSWERED", "NO_ANSWER", "BUSY", "FAILED", "VOICEMAIL", name="CallDisposition"),
            nullable=False,
        ),
        sa.Column("from_number", sa.String(length=32), nullable=False),
        sa.Column("to_number", sa.String(length=32), nullable=False),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column("recording_url", sa.String(length=512), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=True),
        sa.CheckConstraint("btrim(external_id) <> ''", name="calls_external_id_nonempty_check"),
        sa.CheckConstraint("btrim(from_number) <> ''", name="calls_from_number_nonempty_check"),
        sa.CheckConstraint("btrim(to_number) <> ''", name="calls_to_number_nonempty_check"),
        sa.CheckConstraint(
            "deleted_at IS NULL OR deleted_at >= created_at", name="calls_deleted_at_check"
        ),
        sa.CheckConstraint("duration_seconds >= 0", name="calls_duration_nonnegative_check"),
        sa.CheckConstraint("version > 0", name="calls_version_positive_check"),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name="calls_contact_id_fkey", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.id"], name="calls_deal_id_fkey", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="calls_owner_id_fkey", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="calls_pkey"),
        sa.UniqueConstraint("external_id", name="calls_external_id_key"),
    )
    op.create_index("calls_contact_id_idx", "calls", ["contact_id"], unique=False)
    op.create_index("calls_deal_id_idx", "calls", ["deal_id"], unique=False)
    op.create_index("calls_deleted_at_idx", "calls", ["deleted_at"], unique=False)
    op.create_index(
        "calls_direction_disposition_idx", "calls", ["direction", "disposition"], unique=False
    )
    op.create_index(
        "calls_owner_id_started_at_idx", "calls", ["owner_id", "started_at"], unique=False
    )
    op.create_index("calls_started_at_idx", "calls", ["started_at"], unique=False)
    op.create_table(
        "ticket_status_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column(
            "from_status",
            sa.Enum("NEW", "OPEN", "PENDING", "RESOLVED", "CLOSED", name="TicketStatus"),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            sa.Enum("NEW", "OPEN", "PENDING", "RESOLVED", "CLOSED", name="TicketStatus"),
            nullable=False,
        ),
        sa.Column("changed_by_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "changed_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status <> to_status",
            name="ticket_status_logs_status_changed_check",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_id"],
            ["users.id"],
            name="ticket_status_logs_changed_by_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name="ticket_status_logs_ticket_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="ticket_status_logs_pkey"),
    )
    op.create_index(
        "ticket_status_logs_ticket_id_changed_at_idx",
        "ticket_status_logs",
        ["ticket_id", "changed_at"],
        unique=False,
    )
    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("statement_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("booked_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), server_default=sa.text("'USD'"), nullable=False),
        sa.Column(
            "direction", sa.Enum("CREDIT", "DEBIT", name="TransactionDirection"), nullable=False
        ),
        sa.Column("counterparty_name", sa.String(length=200), nullable=False),
        sa.Column("counterparty_account", sa.String(length=64), nullable=True),
        sa.Column("reference", sa.String(length=300), nullable=False),
        sa.Column(
            "match_status",
            sa.Enum("UNMATCHED", "SUGGESTED", "MATCHED", "IGNORED", name="PaymentMatchStatus"),
            server_default=sa.text("'UNMATCHED'"),
            nullable=False,
        ),
        sa.Column("matched_order_id", sa.Uuid(), nullable=True),
        sa.Column("matched_by_id", sa.Uuid(), nullable=True),
        sa.Column("matched_at", postgresql.TIMESTAMP(timezone=True, precision=3), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True, precision=3),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            MATCH_CONSISTENCY_RULE,
            name="bank_transactions_match_consistency_check",
        ),
        sa.CheckConstraint(
            "btrim(counterparty_name) <> ''",
            name="bank_transactions_counterparty_nonempty_check",
        ),
        sa.CheckConstraint(
            "btrim(external_id) <> ''", name="bank_transactions_external_id_nonempty_check"
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="bank_transactions_currency_format_check"
        ),
        sa.CheckConstraint("amount >= 0", name="bank_transactions_amount_nonnegative_check"),
        sa.CheckConstraint("version > 0", name="bank_transactions_version_positive_check"),
        sa.ForeignKeyConstraint(
            ["matched_by_id"],
            ["users.id"],
            name="bank_transactions_matched_by_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["matched_order_id"],
            ["orders.id"],
            name="bank_transactions_matched_order_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["statement_id"],
            ["bank_statements.id"],
            name="bank_transactions_statement_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="bank_transactions_pkey"),
        sa.UniqueConstraint("external_id", name="bank_transactions_external_id_key"),
    )
    op.create_index(
        "bank_transactions_booked_at_idx", "bank_transactions", ["booked_at"], unique=False
    )
    op.create_index(
        "bank_transactions_match_status_booked_at_idx",
        "bank_transactions",
        ["match_status", "booked_at"],
        unique=False,
    )
    op.create_index(
        "bank_transactions_matched_order_id_idx",
        "bank_transactions",
        ["matched_order_id"],
        unique=False,
    )
    op.create_index(
        "bank_transactions_statement_id_booked_at_idx",
        "bank_transactions",
        ["statement_id", "booked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("bank_transactions_statement_id_booked_at_idx", table_name="bank_transactions")
    op.drop_index("bank_transactions_matched_order_id_idx", table_name="bank_transactions")
    op.drop_index("bank_transactions_match_status_booked_at_idx", table_name="bank_transactions")
    op.drop_index("bank_transactions_booked_at_idx", table_name="bank_transactions")
    op.drop_table("bank_transactions")
    op.drop_index("ticket_status_logs_ticket_id_changed_at_idx", table_name="ticket_status_logs")
    op.drop_table("ticket_status_logs")
    op.drop_index("calls_started_at_idx", table_name="calls")
    op.drop_index("calls_owner_id_started_at_idx", table_name="calls")
    op.drop_index("calls_direction_disposition_idx", table_name="calls")
    op.drop_index("calls_deleted_at_idx", table_name="calls")
    op.drop_index("calls_deal_id_idx", table_name="calls")
    op.drop_index("calls_contact_id_idx", table_name="calls")
    op.drop_table("calls")
    op.drop_index("tickets_status_priority_idx", table_name="tickets")
    op.drop_index("tickets_owner_id_status_deleted_at_idx", table_name="tickets")
    op.drop_index("tickets_deleted_at_idx", table_name="tickets")
    op.drop_index("tickets_contact_id_idx", table_name="tickets")
    op.drop_index("tickets_assignee_id_idx", table_name="tickets")
    op.drop_table("tickets")
    op.drop_index("bank_statements_period_start_period_end_idx", table_name="bank_statements")
    op.drop_table("bank_statements")
    for enum_name in ENUM_TYPES:
        op.execute(f'DROP TYPE IF EXISTS "{enum_name}"')
