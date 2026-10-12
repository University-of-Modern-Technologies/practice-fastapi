"""User administration rules.

Anything that changes what a user may do — their roles, or their being disabled
— tells authorization to forget them, so a revoked privilege takes effect on the
next request rather than when a cache entry happens to expire. The cache is
dropped once the change has committed: dropped any earlier, a concurrent request
could read the old rows and cache them again. Every change is also written to
the audit trail on the same session, so the change and its entry commit or roll
back together.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError
from app.core.filters import FilterBuilder
from app.core.paged_query import PagedQuery
from app.core.security import hash_password_async
from app.core.serializers import to_camel
from app.db.models.rbac import Role, UserRole
from app.db.models.user import Session as SessionRow
from app.db.models.user import User
from app.modules.audit import AuditEvent, AuditService
from app.modules.auth.types import (
    NoopSessionRevocationListener,
    SessionRevocationListener,
    notify_sessions_revoked,
)
from app.modules.rbac.commit import after_commit
from app.modules.rbac.types import (
    Actor,
    NoopUserPermissionsInvalidator,
    UserPermissionsInvalidator,
)
from app.modules.users.schemas import (
    CreateUserRequest,
    UpdateUserRequest,
    UserOut,
    UserRoleOut,
    UserSessionOut,
)
from app.modules.users.types import (
    ADMIN_ROLE_NAME,
    CANNOT_DISABLE_SELF,
    EMAIL_ALREADY_EXISTS,
    LAST_ACTIVE_ADMIN,
    SESSION_ENTITY_TYPE,
    SESSION_NOT_FOUND,
    SESSION_REVOKED,
    USER_CREATED,
    USER_DISABLED,
    USER_ENTITY_TYPE,
    USER_NOT_FOUND,
    USER_OR_ROLE_NOT_FOUND,
    USER_UPDATED,
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


def _snapshot(model: UserOut | UserSessionOut) -> dict[str, Any]:
    """The record as the audit trail stores it: the same form the client reads."""
    return model.model_dump(by_alias=True, mode="json")


def _holds_admin_role(user: User) -> bool:
    return any(user_role.role.name == ADMIN_ROLE_NAME for user_role in user.user_roles)


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
        audit: AuditService | None = None,
        sessions: SessionRevocationListener | None = None,
    ) -> None:
        self._session = session
        self._permissions: UserPermissionsInvalidator = (
            permissions if permissions is not None else NoopUserPermissionsInvalidator()
        )
        # The trail is written on this same session, so a change and its entry
        # commit, or roll back, as one.
        self._audit = audit if audit is not None else AuditService(session)
        # Told about sessions a change ended, once it has committed, so a socket
        # opened with one of them is closed now rather than when its token runs out.
        self._sessions: SessionRevocationListener = (
            sessions if sessions is not None else NoopSessionRevocationListener()
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

    async def revoke_session(self, actor: Actor, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        """Ends one session.

        Revoking an already revoked session succeeds: the caller asked for a
        state, and that state holds. Nothing changed, so nothing is audited.
        """
        await self._require_user_exists(user_id)

        row = await self._session.get(SessionRow, session_id)
        if row is None or row.user_id != user_id:
            raise NotFoundError("Session not found", SESSION_NOT_FOUND)
        if row.revoked_at is not None:
            return

        before = _snapshot(to_session_out(row))
        row.revoked_at = datetime.now(tz=UTC)
        await self._flush()
        # The update timestamp is produced by the database.
        await self._session.refresh(row)
        await self._record(
            actor,
            AuditEvent(
                action=SESSION_REVOKED,
                entity_type=SESSION_ENTITY_TYPE,
                entity_id=session_id,
                changes={"before": before, "after": _snapshot(to_session_out(row))},
                metadata={"userId": user_id},
            ),
        )
        await self._end_sessions_after_commit(session_ids=[row.id])

    async def create(self, actor: Actor, data: CreateUserRequest) -> UserOut:
        await self._require_email_available(str(data.email))
        role_ids = list(dict.fromkeys(data.role_ids))
        await self._require_roles_exist(role_ids)

        user = User(
            id=uuid.uuid4(),
            email=str(data.email),
            name=data.name,
            password_hash=await hash_password_async(data.password),
        )
        self._session.add(user)
        await self._flush()

        self._assign_roles(user.id, role_ids)
        await self._flush()

        created = await self.get_by_id(user.id)
        await self._record(
            actor,
            AuditEvent(
                action=USER_CREATED,
                entity_type=USER_ENTITY_TYPE,
                entity_id=user.id,
                changes={"after": _snapshot(created)},
            ),
        )
        await self._forget_permissions_after_commit(user.id)
        return created

    async def update(self, actor: Actor, user_id: uuid.UUID, data: UpdateUserRequest) -> UserOut:
        user = await self._require_user(user_id)
        before = _snapshot(to_user_out(user))
        fields = {name for name in data.model_fields_set if getattr(data, name) is not None}

        if "email" in fields and data.email is not None:
            await self._require_email_available(str(data.email), exclude_id=user_id)
            user.email = str(data.email)
        if "name" in fields and data.name is not None:
            user.name = data.name
        if "password" in fields and data.password is not None:
            user.password_hash = await hash_password_async(data.password)
        if "role_ids" in fields and data.role_ids is not None:
            role_ids = list(dict.fromkeys(data.role_ids))
            await self._require_roles_exist(role_ids)
            await self._guard_admin_role_removal(user, role_ids)
            await self._session.execute(delete(UserRole).where(UserRole.user_id == user_id))
            self._assign_roles(user_id, role_ids)

        await self._flush()
        if "password" in fields:
            # A session opened with the old password must not outlive it: the
            # change is often made precisely because that password leaked.
            await self._revoke_all_sessions(user_id)

        updated = await self.get_by_id(user_id)
        await self._record(
            actor,
            AuditEvent(
                action=USER_UPDATED,
                entity_type=USER_ENTITY_TYPE,
                entity_id=user_id,
                changes={"before": before, "after": _snapshot(updated)},
                # Names only: a password change leaves no trace in the
                # snapshots, and its value has no place in the trail.
                metadata={"changedFields": sorted(to_camel(name) for name in fields)},
            ),
        )
        await self._forget_permissions_after_commit(user_id)
        if "password" in fields:
            await self._end_sessions_after_commit(user_id=user_id)
        return updated

    async def disable(self, actor: Actor, user_id: uuid.UUID) -> UserOut:
        """Deactivates an account and ends every session it holds.

        Both halves matter: leaving the sessions alive would let an already
        issued refresh token keep minting access tokens for a disabled account.
        Two accounts are refused: the caller's own, and the last active holder
        of the admin role. Either would lock administrators out.
        """
        user = await self._require_user(user_id)
        if user_id == actor.actor_id:
            raise ConflictError("You cannot disable your own account", CANNOT_DISABLE_SELF)
        if user.is_active and _holds_admin_role(user):
            admin_role_id = await self._lock_admin_role()
            if admin_role_id is not None:
                await self._require_another_active_admin(admin_role_id, user_id)

        before = _snapshot(to_user_out(user))
        user.is_active = False
        await self._revoke_all_sessions(user_id)
        await self._flush()

        disabled = await self.get_by_id(user_id)
        await self._record(
            actor,
            AuditEvent(
                action=USER_DISABLED,
                entity_type=USER_ENTITY_TYPE,
                entity_id=user_id,
                changes={"before": before, "after": _snapshot(disabled)},
            ),
        )
        await self._forget_permissions_after_commit(user_id)
        await self._end_sessions_after_commit(user_id=user_id)
        return disabled

    async def _forget_permissions_after_commit(self, user_id: uuid.UUID) -> None:
        async def forget() -> None:
            await self._permissions.invalidate_user_permissions(user_id)

        await after_commit(self._session, forget)

    async def _end_sessions_after_commit(
        self, *, session_ids: Sequence[uuid.UUID] = (), user_id: uuid.UUID | None = None
    ) -> None:
        ended_ids = list(session_ids)

        async def notify() -> None:
            notify_sessions_revoked(self._sessions, session_ids=ended_ids, user_id=user_id)

        await after_commit(self._session, notify)

    async def _flush(self) -> None:
        """Surfaces a constraint violation as the conflict it represents."""
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise ConflictError(
                "A user with this email already exists", EMAIL_ALREADY_EXISTS
            ) from error

    async def _record(self, actor: Actor, event: AuditEvent) -> None:
        """Appends an entry attributed to the caller to this transaction."""
        await self._audit.record(
            replace(event, actor_id=actor.actor_id, ip_address=actor.ip_address)
        )

    async def _revoke_all_sessions(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            update(SessionRow)
            .where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
            .values(revoked_at=datetime.now(tz=UTC))
        )

    async def _guard_admin_role_removal(self, user: User, role_ids: list[uuid.UUID]) -> None:
        """Refuses a role change that takes the admin role from its last active holder."""
        if not user.is_active or not _holds_admin_role(user):
            return
        admin_role_id = await self._lock_admin_role()
        if admin_role_id is None or admin_role_id in role_ids:
            return
        await self._require_another_active_admin(admin_role_id, user.id)

    async def _lock_admin_role(self) -> uuid.UUID | None:
        """Locks the admin role row for the rest of the transaction.

        Every change that could leave the role without an active holder takes
        this lock first, so two administrators disabling each other at the same
        moment are serialised instead of each seeing the other still active.
        """
        admin_role_id: uuid.UUID | None = await self._session.scalar(
            select(Role.id).where(Role.name == ADMIN_ROLE_NAME).with_for_update()
        )
        return admin_role_id

    async def _require_another_active_admin(
        self, admin_role_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        others = await self._session.scalar(
            select(func.count())
            .select_from(UserRole)
            .join(User, User.id == UserRole.user_id)
            .where(
                UserRole.role_id == admin_role_id,
                UserRole.user_id != user_id,
                User.is_active.is_(True),
            )
        )
        if not others:
            raise ConflictError(
                "The last active administrator cannot be disabled or lose the admin role",
                LAST_ACTIVE_ADMIN,
            )

    def _assign_roles(self, user_id: uuid.UUID, role_ids: list[uuid.UUID]) -> None:
        for role_id in dict.fromkeys(role_ids):
            self._session.add(UserRole(user_id=user_id, role_id=role_id))

    async def _require_user(self, user_id: uuid.UUID) -> User:
        result = await self._session.execute(
            select(User)
            .options(_ROLES)
            .where(User.id == user_id)
            # An account already in the session is reloaded, roles included:
            # a read that follows a change in the same request must see the
            # change, not the copy that was loaded before it.
            .execution_options(populate_existing=True)
        )
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
