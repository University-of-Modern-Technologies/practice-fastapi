"""Organization-wide configuration held in the database."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import CreatedAt, UpdatedAt, UuidPk

if TYPE_CHECKING:
    from app.db.models.user import User


class OrganizationSetting(Base):
    """One configuration entry, addressed by a dotted key."""

    __tablename__ = "organization_settings"

    id: Mapped[UuidPk]
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    # JSON rather than text: a setting may be a scalar, a list or an object,
    # and the API returns it unchanged.
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    updated_by: Mapped[User | None] = relationship(back_populates="setting_edits", lazy="raise")

    __table_args__ = (UniqueConstraint("key"),)
