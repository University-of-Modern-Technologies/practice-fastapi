"""User administration rules.

Anything that changes what a user may do — their roles, or their being disabled
— tells authorization to forget them, so a revoked privilege takes effect on the
next request rather than when a cache entry happens to expire.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError
from app.core.filters import FilterBuilder
from app.core.paged_query import PagedQuery
from app.core.security import hash_password
from app.db.models.rbac import Role, UserRole
from app.db.models.user import Session as SessionRow
from app.db.models.user import User
from app.modules.rbac.types import NoopUserPermissionsInvalidator, UserPermissionsInvalidator
from app.modules.users.schemas import (
    CreateUserRequest,
    UpdateUserRequest,
    UserOut,
    UserRoleOut,
    UserSessionOut,
)
from app.modules.users.types import (
    EMAIL_ALREADY_EXISTS,
    SESSION_NOT_FOUND,
    USER_NOT_FOUND,
    USER_OR_ROLE_NOT_FOUND,
)

_ROLES = selectinload(User.user_roles).selectinload(UserRole.role)


def to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        roles=[
            UserRoleOut(id=user_role.role.id, name=user_role.role.name)
            for user_role in user.user_roles
        ],
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def to_session_out(row: SessionRow) -> UserSessionOut:
    """Renders a session without the token digest it is keyed on."""
    return UserSessionOut(
        id=row.id,
        user_id=row.user_id,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        ip_address=row.ip_address,
        user_agent=row.user_agent,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@dataclass(frozen=True, slots=True)
class _UsersPageParams:
    """The public ``list_users`` signature takes plain arguments, not an
    object; this is that call bundled into what the page query needs."""

    page: int
    page_size: int
    owner_id: uuid.UUID | None = None


class _UsersPage(PagedQuery[User, _UsersPageParams, UserOut]):
    """One page of accounts, newest first."""

    def _model(self) -> type[User]:
        return User

    def _build_filters(self, params: _UsersPageParams) -> list[ColumnElement[bool]]:
        return FilterBuilder().equals(User.id, params.owner_id).build()

    def _order_by(self, _params: _UsersPageParams) -> tuple[ColumnElement[Any], ...]:
        return (User.created_at.desc(),)

    def _load_options(self) -> Sequence[Any]:
        return (_ROLES,)

    def _distinct_rows(self) -> bool:
        return True

    def _to_dto(self, row: User) -> UserOut:
        return to_user_out(row)


class UsersService:
    """Reads and writes accounts, their roles and their sessions."""

    def __init__(
        self,
        session: AsyncSession,
        permissions: UserPermissionsInvalidator | None = None,
    ) -> None:
        self._session = session
        self._permissions: UserPermissionsInvalidator = (
            permissions if permissions is not None else NoopUserPermissionsInvalidator()
        )

    async def list_users(
        self, page: int, page_size: int, owner_id: uuid.UUID | None = None
    ) -> tuple[list[UserOut], int]:
        """One page of accounts, newest first.

        ``owner_id`` narrows the page to a single account; it is what a caller
        holding only ``OWN`` is allowed to see.
        """
        return await _UsersPage(self._session).run(_UsersPageParams(page, page_size, owner_id))

    async def get_by_id(self, user_id: uuid.UUID) -> UserOut:
        user = await self._require_user(user_id)
        return to_user_out(user)

    async def list_sessions(self, user_id: uuid.UUID) -> list[UserSessionOut]:
        await self._require_user_exists(user_id)
        result = await self._session.execute(
            select(SessionRow)
            .where(SessionRow.user_id == user_id)
            .order_by(SessionRow.created_at.desc())
        )
        return [to_session_out(row) for row in result.scalars().all()]

    async def revoke_session(self, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        """Ends one session.

        Revoking an already revoked session succeeds: the caller asked for a
        state, and that state holds.
        """
        await self._require_user_exists(user_id)

        row = await self._session.get(SessionRow, session_id)
        if row is None or row.user_id != user_id:
            raise NotFoundError("Session not found", SESSION_NOT_FOUND)
        if row.revoked_at is None:
            row.revoked_at = datetime.now(tz=UTC)
            await self._flush()

    async def create(self, data: CreateUserRequest) -> UserOut:
        await self._require_email_available(str(data.email))
        await self._require_roles_exist(data.role_ids)

        user = User(
            id=uuid.uuid4(),
            email=str(data.email),
            name=data.name,
            password_hash=hash_password(data.password),
        )
        self._session.add(user)
        await self._flush()

        self._assign_roles(user.id, data.role_ids)
        await self._flush()

        await self._permissions.invalidate_user_permissions(user.id)
        return await self.get_by_id(user.id)

    async def update(self, user_id: uuid.UUID, data: UpdateUserRequest) -> UserOut:
        user = await self._require_user(user_id)
        fields = data.model_fields_set

        if "email" in fields and data.email is not None:
            await self._require_email_available(str(data.email), exclude_id=user_id)
            user.email = str(data.email)
        if "name" in fields and data.name is not None:
            user.name = data.name
        if "password" in fields and data.password is not None:
            user.password_hash = hash_password(data.password)
        if "role_ids" in fields and data.role_ids is not None:
            await self._require_roles_exist(data.role_ids)
            await self._session.execute(delete(UserRole).where(UserRole.user_id == user_id))
            self._assign_roles(user_id, data.role_ids)

        await self._flush()
        await self._permissions.invalidate_user_permissions(user_id)
        return await self.get_by_id(user_id)

    async def disable(self, user_id: uuid.UUID) -> UserOut:
        """Deactivates an account and ends every session it holds.

        Both halves matter: leaving the sessions alive would let an already
        issued refresh token keep minting access tokens for a disabled account.
        """
        user = await self._require_user(user_id)
        user.is_active = False
        await self._session.execute(
            update(SessionRow)
            .where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
            .values(revoked_at=datetime.now(tz=UTC))
        )
        await self._flush()

        await self._permissions.invalidate_user_permissions(user_id)
        return await self.get_by_id(user_id)

    async def _flush(self) -> None:
        """Surfaces a constraint violation as the conflict it represents."""
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise ConflictError(
                "A user with this email already exists", EMAIL_ALREADY_EXISTS
            ) from error

    def _assign_roles(self, user_id: uuid.UUID, role_ids: list[uuid.UUID]) -> None:
        for role_id in dict.fromkeys(role_ids):
            self._session.add(UserRole(user_id=user_id, role_id=role_id))

    async def _require_user(self, user_id: uuid.UUID) -> User:
        result = await self._session.execute(select(User).options(_ROLES).where(User.id == user_id))
        user = result.scalars().unique().one_or_none()
        if user is None:
            raise NotFoundError("User not found", USER_NOT_FOUND)
        return user

    async def _require_user_exists(self, user_id: uuid.UUID) -> None:
        if await self._session.scalar(select(User.id).where(User.id == user_id)) is None:
            raise NotFoundError("User not found", USER_NOT_FOUND)

    async def _require_email_available(
        self, email: str, exclude_id: uuid.UUID | None = None
    ) -> None:
        criteria = [User.email == email]
        if exclude_id is not None:
            criteria.append(User.id != exclude_id)
        if await self._session.scalar(select(User.id).where(*criteria)) is not None:
            raise ConflictError("A user with this email already exists", EMAIL_ALREADY_EXISTS)

    async def _require_roles_exist(self, role_ids: list[uuid.UUID]) -> None:
        result = await self._session.execute(select(Role.id).where(Role.id.in_(role_ids)))
        found = set(result.scalars().all())
        if any(role_id not in found for role_id in role_ids):
            raise NotFoundError("User or role not found", USER_OR_ROLE_NOT_FOUND)
