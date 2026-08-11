"""Append-only trail of state-changing operations."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import CreatedAt, IpAddress, Json, UuidPk

if TYPE_CHECKING:
    from app.db.models.user import User


class AuditLog(Base):
    """One recorded action. Rows are written once and never modified."""

    __tablename__ = "audit_logs"

    id: Mapped[UuidPk]
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID | None]
    changes: Mapped[Json]
    # ``metadata`` is reserved by the declarative base, so the attribute is
    # renamed while the column keeps the name the API contract uses.
    meta: Mapped[Json] = mapped_column("metadata")
    ip_address: Mapped[IpAddress]
    created_at: Mapped[CreatedAt]

    actor: Mapped[User | None] = relationship(back_populates="audit_logs", lazy="raise")

    __table_args__ = (
        Index(None, "actor_id", "created_at"),
        Index(None, "entity_type", "entity_id", "created_at"),
        Index(None, "action", "created_at"),
        CheckConstraint("btrim(action) <> ''", name="action_nonempty"),
        CheckConstraint("btrim(entity_type) <> ''", name="entity_type_nonempty"),
    )
