"""Fixture revision, used only by test_health_database.py."""

from __future__ import annotations

revision: str = "0001_fixture"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:  # pragma: no cover - never executed, read for its metadata only
    pass


def downgrade() -> None:  # pragma: no cover - never executed, read for its metadata only
    pass
