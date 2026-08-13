"""Authentication rules, exercised without a database.

The session is replaced by a scripted double so that the properties under test
are the ones the service is responsible for — credential handling, session
rotation and token verification — rather than SQL.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.core.security import hash_password
from app.db.enums import PermissionScope
from app.db.models.rbac import Permission, Role, RolePermission, UserRole
from app.db.models.user import Session as SessionRow
from app.db.models.user import User
from app.modules.auth.schemas import LoginRequest
from app.modules.auth.service import AuthService, split_refresh_token, to_authenticated_user
from app.modules.auth.types import AuthConfig

PASSWORD = "correct-horse"
PASSWORD_HASH = hash_password(PASSWORD)

CONFIG = AuthConfig(
    access_token_secret="unit-test-secret-value-long-enough",
    secure_cookies=False,
)


class FakeResult:
    def __init__(self, value: Any = None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    """The slice of ``AsyncSession`` the auth service actually calls."""

    def __init__(self, *, found_user: User | None = None) -> None:
        self.found_user = found_user
        self.rows: dict[Any, Any] = {}
        self.added: list[Any] = []
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.found_user)

    async def get(self, model: Any, primary_key: Any) -> Any:
        return self.rows.get((model, primary_key))

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        return None


def make_service(session: FakeSession) -> AuthService:
    return AuthService(cast("AsyncSession", session), CONFIG)


def make_user(
    *, is_active: bool = True, grants: list[tuple[str, PermissionScope]] | None = None
) -> User:
    role = Role(
        id=uuid.uuid4(),
        name="manager",
        permissions=[
            RolePermission(scope=scope, permission=Permission(id=uuid.uuid4(), key=key))
            for key, scope in (grants or [])
        ],
    )
    return User(
        id=uuid.uuid4(),
        email="morgan@example.com",
        name="Morgan Manager",
        password_hash=PASSWORD_HASH,
        is_active=is_active,
        user_roles=[UserRole(role=role)],
    )


def make_session_row(
    user: User, secret: str, *, revoked: bool = False, expired: bool = False
) -> SessionRow:
    now = datetime.now(tz=UTC)
    return SessionRow(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=hash_password(secret),
        expires_at=now - timedelta(days=1) if expired else now + timedelta(days=7),
        revoked_at=now if revoked else None,
        created_at=now,
        updated_at=now,
    )


def test_permissions_are_deduplicated_with_the_widest_scope_winning() -> None:
    user = make_user(
        grants=[
            ("contacts:read", PermissionScope.OWN),
            ("contacts:read", PermissionScope.ALL),
            ("deals:write", PermissionScope.OWN),
        ]
    )

    permissions = {
        (grant.resource, grant.action): grant.scope
        for grant in to_authenticated_user(user).permissions
    }

    assert permissions == {
        ("contacts", "read"): PermissionScope.ALL,
        ("deals", "write"): PermissionScope.OWN,
    }


def test_an_all_grant_is_not_overwritten_by_a_later_own_grant() -> None:
    user = make_user(
        grants=[("contacts:read", PermissionScope.ALL), ("contacts:read", PermissionScope.OWN)]
    )

    assert to_authenticated_user(user).permissions[0].scope == PermissionScope.ALL


def test_unreadable_permission_keys_are_ignored_rather_than_guessed() -> None:
    user = make_user(grants=[("broken", PermissionScope.ALL), ("a:b:c", PermissionScope.ALL)])

    assert to_authenticated_user(user).permissions == []


def test_refresh_token_splits_into_session_and_secret() -> None:
    session_id = uuid.uuid4()

    parsed_id, secret = split_refresh_token(f"{session_id}.abc.def")

    assert parsed_id == session_id
    assert secret == "abc.def"


@pytest.mark.parametrize(
    "token",
    ["", ".", "no-separator", f"{uuid.uuid4()}.", f".{uuid.uuid4()}", "not-a-uuid.secret"],
)
def test_malformed_refresh_tokens_are_rejected(token: str) -> None:
    with pytest.raises(UnauthorizedError) as error:
        split_refresh_token(token)

    assert error.value.code == "INVALID_REFRESH_TOKEN"


@pytest.mark.parametrize(
    ("user", "password"),
    [
        (None, PASSWORD),
        (make_user(), "wrong-password"),
        (make_user(is_active=False), PASSWORD),
    ],
    ids=["unknown-email", "wrong-password", "disabled-account"],
)
async def test_every_failed_login_answers_identically(user: User | None, password: str) -> None:
    service = make_service(FakeSession(found_user=user))

    with pytest.raises(UnauthorizedError) as error:
        await service.login(LoginRequest(email="morgan@example.com", password=password))

    assert error.value.status_code == 401
    assert error.value.code == "INVALID_CREDENTIALS"


async def test_login_opens_a_session_and_returns_a_matching_token_pair() -> None:
    user = make_user(grants=[("contacts:read", PermissionScope.ALL)])
    session = FakeSession(found_user=user)

    result = await make_service(session).login(
        LoginRequest(email="MORGAN@Example.com ", password=PASSWORD)
    )

    row = session.added[0]
    assert isinstance(row, SessionRow)
    assert row.user_id == user.id

    session_id, secret = result.refresh_token.split(".", 1)
    assert uuid.UUID(session_id) == row.id
    # Only the digest is stored, so a database leak does not hand out sessions.
    assert row.token_hash != secret

    claims = jwt.decode(result.access_token, CONFIG.access_token_secret, algorithms=["HS256"])
    assert claims["sub"] == str(user.id)
    assert claims["sessionId"] == str(row.id)
    assert claims["type"] == "access"
    assert result.access_token_expires_in_seconds == 900


async def test_refresh_rotates_the_secret_of_the_same_session() -> None:
    user = make_user()
    secret = "original-secret"
    row = make_session_row(user, secret, revoked=False)
    original_hash = row.token_hash

    session = FakeSession(found_user=user)
    session.rows[(SessionRow, row.id)] = row

    result = await make_service(session).refresh(f"{row.id}.{secret}")

    assert result.refresh_token.startswith(f"{row.id}.")
    assert result.refresh_token != f"{row.id}.{secret}"
    assert row.token_hash != original_hash
    assert row.revoked_at is None
    assert row.expires_at > datetime.now(tz=UTC) + timedelta(days=6)
    # Rotation reuses the row, so a device does not accumulate sessions.
    assert session.added == []


@pytest.mark.parametrize(
    ("revoked", "expired", "secret"),
    [(True, False, "s"), (False, True, "s"), (False, False, "wrong")],
    ids=["revoked", "expired", "wrong-secret"],
)
async def test_an_unusable_session_cannot_be_refreshed(
    revoked: bool, expired: bool, secret: str
) -> None:
    user = make_user()
    row = make_session_row(user, "s", revoked=revoked, expired=expired)
    session = FakeSession(found_user=user)
    session.rows[(SessionRow, row.id)] = row

    with pytest.raises(UnauthorizedError) as error:
        await make_service(session).refresh(f"{row.id}.{secret}")

    assert error.value.code == "INVALID_REFRESH_TOKEN"


async def test_logout_without_a_token_is_not_an_error() -> None:
    session = FakeSession()

    await make_service(session).logout(None)
    await make_service(session).logout("")
    await make_service(session).logout("garbage")

    # Nothing was written: there was no session to end.
    assert session.statements == []


async def test_logout_revokes_the_addressed_session() -> None:
    session = FakeSession()

    await make_service(session).logout(f"{uuid.uuid4()}.secret")

    assert len(session.statements) == 1


async def test_authenticate_accepts_a_token_backed_by_a_live_session() -> None:
    user = make_user()
    row = make_session_row(user, "s")
    session = FakeSession(found_user=user)
    session.rows[(SessionRow, row.id)] = row
    session.rows[(User, user.id)] = user

    token = jwt.encode(
        {
            "sub": str(user.id),
            "sessionId": str(row.id),
            "type": "access",
            "exp": datetime.now(tz=UTC) + timedelta(minutes=15),
        },
        CONFIG.access_token_secret,
        algorithm="HS256",
    )

    auth = await make_service(session).authenticate(token)

    assert auth.user_id == user.id
    assert auth.session_id == row.id


@pytest.mark.parametrize(
    "claims",
    [
        {"type": "refresh"},
        {"sessionId": None},
        {"sub": "not-a-uuid"},
    ],
    ids=["wrong-token-type", "missing-session", "unparsable-subject"],
)
async def test_a_token_with_unusable_claims_is_unauthorized(claims: dict[str, Any]) -> None:
    user = make_user()
    row = make_session_row(user, "s")
    session = FakeSession(found_user=user)
    session.rows[(SessionRow, row.id)] = row
    session.rows[(User, user.id)] = user

    payload: dict[str, Any] = {
        "sub": str(user.id),
        "sessionId": str(row.id),
        "type": "access",
        "exp": datetime.now(tz=UTC) + timedelta(minutes=15),
        **claims,
    }
    token = jwt.encode(payload, CONFIG.access_token_secret, algorithm="HS256")

    with pytest.raises(UnauthorizedError) as error:
        await make_service(session).authenticate(token)

    assert error.value.code == "UNAUTHORIZED"


async def test_a_disabled_account_loses_access_before_its_token_expires() -> None:
    user = make_user(is_active=False)
    row = make_session_row(user, "s")
    session = FakeSession(found_user=user)
    session.rows[(SessionRow, row.id)] = row
    session.rows[(User, user.id)] = user

    token = jwt.encode(
        {
            "sub": str(user.id),
            "sessionId": str(row.id),
            "type": "access",
            "exp": datetime.now(tz=UTC) + timedelta(minutes=15),
        },
        CONFIG.access_token_secret,
        algorithm="HS256",
    )

    with pytest.raises(UnauthorizedError) as error:
        await make_service(session).authenticate(token)

    assert error.value.code == "UNAUTHORIZED"


async def test_an_expired_token_is_rejected_without_touching_the_database() -> None:
    session = FakeSession()
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "sessionId": str(uuid.uuid4()),
            "type": "access",
            "exp": datetime.now(tz=UTC) - timedelta(seconds=1),
        },
        CONFIG.access_token_secret,
        algorithm="HS256",
    )

    with pytest.raises(UnauthorizedError):
        await make_service(session).authenticate(token)

    assert session.statements == []


async def test_me_refuses_a_deactivated_account() -> None:
    session = FakeSession(found_user=make_user(is_active=False))

    with pytest.raises(UnauthorizedError) as error:
        await make_service(session).me(uuid.uuid4())

    assert error.value.code == "USER_UNAVAILABLE"
