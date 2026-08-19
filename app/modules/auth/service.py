"""Authentication rules.

The service owns three secrets-related decisions and nothing else: how a
password is checked, how a session is issued and rotated, and how an access
token is turned back into an identity. It never touches HTTP — cookies and
status codes are the router's business.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.enums import PermissionScope
from app.db.models.rbac import Role, RolePermission, UserRole
from app.db.models.user import Session as SessionRow
from app.db.models.user import User
from app.modules.auth.schemas import AuthenticatedUser, LoginRequest, PermissionOut
from app.modules.auth.types import (
    REFRESH_SECRET_BYTES,
    REFRESH_TOKEN_SEPARATOR,
    AuthConfig,
    AuthContext,
    AuthResult,
)
from app.modules.rbac.types import create_permission_key, parse_permission_key

#: Eager-loads the role graph in one round trip. The relationships are declared
#: ``lazy="raise"``, so an authorization decision cannot accidentally become a
#: sequence of queries hidden behind attribute access.
_ROLE_GRAPH = (
    selectinload(User.user_roles)
    .selectinload(UserRole.role)
    .selectinload(Role.permissions)
    .selectinload(RolePermission.permission)
)


def _as_aware(moment: datetime) -> datetime:
    """Reads a timestamp as UTC when the driver dropped the zone."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def to_authenticated_user(user: User) -> AuthenticatedUser:
    """Flattens the role graph into the shape the client consumes.

    The same permission may arrive through several roles at different breadths;
    the widest grant wins, because a narrower one cannot take away what another
    role already allows.
    """
    grants: dict[str, PermissionOut] = {}
    roles: list[str] = []

    for user_role in user.user_roles:
        role = user_role.role
        roles.append(role.name)
        for grant in role.permissions:
            parts = parse_permission_key(grant.permission.key)
            if parts is None:
                continue
            key = create_permission_key(parts.resource, parts.action)
            if key not in grants or grant.scope == PermissionScope.ALL:
                grants[key] = PermissionOut(
                    resource=parts.resource, action=parts.action, scope=grant.scope
                )

    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        name=user.name,
        roles=roles,
        permissions=list(grants.values()),
    )


def split_refresh_token(token: str) -> tuple[uuid.UUID, str]:
    """Splits ``"{session_id}.{secret}"`` into its two halves.

    The session id travels in clear text so the row can be located; only the
    secret is ever compared, and only against its stored digest.
    """
    separator = token.find(REFRESH_TOKEN_SEPARATOR)
    if separator < 1 or separator == len(token) - 1:
        raise UnauthorizedError("Invalid refresh token", "INVALID_REFRESH_TOKEN")
    try:
        session_id = uuid.UUID(token[:separator])
    except ValueError as error:
        raise UnauthorizedError("Invalid refresh token", "INVALID_REFRESH_TOKEN") from error
    return session_id, token[separator + 1 :]


class AuthService:
    """Sign-in, session rotation and access-token verification."""

    def __init__(self, session: AsyncSession, config: AuthConfig) -> None:
        self._session = session
        self._config = config

    async def login(self, data: LoginRequest) -> AuthResult:
        """Verifies credentials and opens a new session.

        A missing account, a wrong password and a disabled account are reported
        identically: any difference between them turns the endpoint into a way
        of enumerating who has an account here.
        """
        user = await self._find_user_by_email(str(data.email))
        if (
            user is None
            or not user.is_active
            or not verify_password(data.password, user.password_hash)
        ):
            raise UnauthorizedError("Invalid email or password", "INVALID_CREDENTIALS")
        return await self._issue(user)

    async def refresh(self, refresh_token: str) -> AuthResult:
        """Rotates the secret of an existing session.

        Rotation reuses the same row, so a stolen token stops working the moment
        the legitimate holder refreshes — and the client keeps one session in
        its device list rather than accumulating one per refresh.
        """
        session_id, secret = split_refresh_token(refresh_token)
        row = await self._session.get(SessionRow, session_id)
        if row is None or not self._is_usable(row) or not verify_password(secret, row.token_hash):
            raise UnauthorizedError("Invalid refresh token", "INVALID_REFRESH_TOKEN")

        user = await self._find_user_by_id(row.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("Invalid refresh token", "INVALID_REFRESH_TOKEN")

        return await self._issue(user, row)

    async def logout(self, refresh_token: str | None) -> None:
        """Revokes the session a refresh token points at.

        Logging out without a usable token is not an error: the caller asked to
        end a session that is already over, and the outcome they wanted holds.
        """
        if not refresh_token:
            return
        try:
            session_id, _ = split_refresh_token(refresh_token)
        except UnauthorizedError:
            return

        await self._session.execute(
            update(SessionRow)
            .where(SessionRow.id == session_id, SessionRow.revoked_at.is_(None))
            .values(revoked_at=datetime.now(tz=UTC))
        )

    async def authenticate(self, access_token: str) -> AuthContext:
        """Turns a bearer token into an identity.

        Every failure collapses into one 401: the token being expired, the
        session revoked or the account disabled are all "you are not signed in"
        from the client's side, and distinguishing them leaks state.
        """
        try:
            claims = decode_access_token(access_token, self._config.access_token_secret)
        except jwt.PyJWTError as error:
            raise UnauthorizedError() from error

        subject = claims.get("sub")
        raw_session_id = claims.get("sessionId")
        if claims.get("type") != "access" or not isinstance(subject, str):
            raise UnauthorizedError()
        if not isinstance(raw_session_id, str):
            raise UnauthorizedError()

        try:
            user_id = uuid.UUID(subject)
            session_id = uuid.UUID(raw_session_id)
        except ValueError as error:
            raise UnauthorizedError() from error

        row = await self._session.get(SessionRow, session_id)
        if row is None or row.user_id != user_id or not self._is_usable(row):
            raise UnauthorizedError()

        user = await self._session.get(User, user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError()

        return AuthContext(user_id=user_id, session_id=session_id)

    async def me(self, user_id: uuid.UUID) -> AuthenticatedUser:
        """The signed-in account with its roles and full permission list."""
        user = await self._find_user_by_id(user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("User is unavailable", "USER_UNAVAILABLE")
        return to_authenticated_user(user)

    def _is_usable(self, row: SessionRow) -> bool:
        return row.revoked_at is None and _as_aware(row.expires_at) > datetime.now(tz=UTC)

    async def _find_user_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).options(_ROLE_GRAPH).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def _find_user_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._session.execute(
            select(User).options(_ROLE_GRAPH).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def _issue(self, user: User, row: SessionRow | None = None) -> AuthResult:
        """Writes a fresh refresh secret and signs a matching access token."""
        secret = secrets.token_urlsafe(REFRESH_SECRET_BYTES)
        token_hash = hash_password(secret)
        expires_at = datetime.now(tz=UTC) + timedelta(
            seconds=self._config.refresh_token_ttl_seconds
        )

        if row is None:
            row = SessionRow(
                id=uuid.uuid4(),
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            self._session.add(row)
        else:
            row.token_hash = token_hash
            row.expires_at = expires_at
            # A refresh on a revoked-but-still-valid row would otherwise hand
            # out a token the next request rejects.
            row.revoked_at = None

        await self._session.flush()

        access_token = create_access_token(
            subject=str(user.id),
            session_id=str(row.id),
            secret=self._config.access_token_secret,
            ttl_seconds=self._config.access_token_ttl_seconds,
        )
        return AuthResult(
            user=to_authenticated_user(user),
            access_token=access_token,
            refresh_token=f"{row.id}{REFRESH_TOKEN_SEPARATOR}{secret}",
            access_token_expires_in_seconds=self._config.access_token_ttl_seconds,
        )
