"""Roles, permissions and the two join tables that connect them.

A grant carries a scope, so "may read deals" and "may read *own* deals" are the
same permission with a different reach rather than two separate keys.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import PermissionScope, pg_enum
from app.db.types import CreatedAt, UpdatedAt, UuidFk, UuidPk

if TYPE_CHECKING:
    from app.db.models.user import User

#: A permission key looks like ``contacts:read`` — a lowercase subject and verb.
PERMISSION_KEY_PATTERN = "^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$"


class Role(Base):
    """A named bundle of permission grants."""

    __tablename__ = "roles"

    id: Mapped[UuidPk]
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    user_roles: Mapped[list[UserRole]] = relationship(
        back_populates="role", lazy="raise", passive_deletes=True
    )
    permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("name"),
        CheckConstraint("btrim(name) <> ''", name="name_nonempty"),
    )


class Permission(Base):
    """A single capability the API can check for."""

    __tablename__ = "permissions"

    id: Mapped[UuidPk]
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    roles: Mapped[list[RolePermission]] = relationship(
        back_populates="permission", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("key"),
        CheckConstraint(f"key ~ '{PERMISSION_KEY_PATTERN}'", name="key_format"),
    )


class UserRole(Base):
    """Assignment of a role to a user."""

    __tablename__ = "user_roles"

    user_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[CreatedAt]

    user: Mapped[User] = relationship(back_populates="user_roles", lazy="raise")
    role: Mapped[Role] = relationship(back_populates="user_roles", lazy="raise")

    __table_args__ = (Index(None, "role_id"),)


class RolePermission(Base):
    """Grant of one permission to one role, at a given scope."""

    __tablename__ = "role_permissions"

    role_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[UuidFk] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[PermissionScope] = mapped_column(
        pg_enum(PermissionScope, "PermissionScope"), nullable=False
    )
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    role: Mapped[Role] = relationship(back_populates="permissions", lazy="raise")
    permission: Mapped[Permission] = relationship(back_populates="roles", lazy="raise")

    __table_args__ = (Index(None, "permission_id"),)
