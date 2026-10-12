"""Authentication rules, exercised without a database.

The session is replaced by a scripted double so that the properties under test
are the ones the service is responsible for — credential handling, session
rotation and token verification — rather than SQL.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import jwt
import pytest
from fastapi import Request
from pydantic import ValidationError
from sqlalchemy import Update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.errors import UnauthorizedError
from app.core.security import (
    BCRYPT_ROUNDS,
    DUMMY_PASSWORD_HASH,
    hash_password,
    hash_password_async,
    verify_password,
    verify_password_async,
)
from app.db.enums import PermissionScope
from app.db.models.rbac import Permission, Role, RolePermission, UserRole
from app.db.models.user import Session as SessionRow
from app.db.models.user import User
from app.modules.auth import service as auth_service_module
from app.modules.auth.dependencies import get_session_revocations
from app.modules.auth.schemas import LoginRequest
from app.modules.auth.service import AuthService, split_refresh_token, to_authenticated_user
from app.modules.auth.types import AuthConfig, ClientInfo, NoopSessionRevocationListener

PASSWORD = "correct-horse"
PASSWORD_HASH = hash_password(PASSWORD)

CONFIG = AuthConfig(
    access_token_secret="unit-test-secret-value-long-enough",
    secure_cookies=False,
)


class FakeResult:
    def __init__(self, value: Any = None, rowcount: int = 1) -> None:
        self._value = value
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    """The slice of ``AsyncSession`` the auth service actually calls."""

    def __init__(self, *, found_user: User | None = None) -> None:
        self.found_user = found_user
        self.rows: dict[Any, Any] = {}
        self.added: list[Any] = []
        self.statements: list[Any] = []
        #: Rows an UPDATE reports as matched; zero stands for a row that a
        #: concurrent request revoked between the read and the write.
        self.rowcount = 1

    async def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.found_user, self.rowcount)

    async def get(self, model: Any, primary_key: Any) -> Any:
        return self.rows.get((model, primary_key))

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        return None


def make_service(session: FakeSession, client: ClientInfo | None = None) -> AuthService:
    return AuthService(cast("AsyncSession", session), CONFIG, client)


def update_values(statement: Update) -> dict[str, Any]:
    """The columns an UPDATE sets, by attribute name, with the values it binds."""
    values: dict[Any, Any] = cast("Any", statement)._values
    return {column.key: value.value for column, value in values.items()}


def session_updates(session: FakeSession) -> list[Update]:
    return [
        statement
        for statement in session.statements
        if isinstance(statement, Update) and getattr(statement.table, "name", None) == "sessions"
    ]


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
    [
        "",
        ".",
        "no-separator",
        f"{uuid.uuid4()}.",
        f".{uuid.uuid4()}",
        "not-a-uuid.secret",
        f"{uuid.uuid4().hex}.secret",
        f"{{{uuid.uuid4()}}}.secret",
        f"urn:uuid:{uuid.uuid4()}.secret",
    ],
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
    [rotation] = session_updates(session)
    values = update_values(rotation)
    assert values["token_hash"] != original_hash
    assert verify_password(result.refresh_token.split(".", 1)[1], values["token_hash"])
    assert values["expires_at"] > datetime.now(tz=UTC) + timedelta(days=6)
    # Rotation reuses the row, so a device does not accumulate sessions.
    assert session.added == []


# A refresh must never bring a revoked session back.
async def test_rotation_never_clears_a_revocation_and_is_guarded_on_it() -> None:
    user = make_user()
    row = make_session_row(user, "s")
    session = FakeSession(found_user=user)
    session.rows[(SessionRow, row.id)] = row

    await make_service(session).refresh(f"{row.id}.s")

    [rotation] = session_updates(session)
    assert "revoked_at" not in update_values(rotation)
    assert "sessions.revoked_at IS NULL" in str(rotation.whereclause)


async def test_a_session_revoked_while_the_refresh_was_in_flight_stays_revoked() -> None:
    user = make_user()
    row = make_session_row(user, "s")
    session = FakeSession(found_user=user)
    session.rows[(SessionRow, row.id)] = row
    session.rowcount = 0  # the guarded write matched nothing

    with pytest.raises(UnauthorizedError) as error:
        await make_service(session).refresh(f"{row.id}.s")

    assert error.value.code == "INVALID_REFRESH_TOKEN"


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


class RecordingRevocations:
    """Collects what the service reports about sessions it ended."""

    def __init__(self) -> None:
        self.sessions: list[uuid.UUID] = []
        self.users: list[uuid.UUID] = []

    def sessions_revoked(self, session_ids: Sequence[uuid.UUID]) -> None:
        self.sessions.extend(session_ids)

    def user_sessions_revoked(self, user_id: uuid.UUID) -> None:
        self.users.append(user_id)


async def test_logout_revokes_the_addressed_session() -> None:
    row = make_session_row(make_user(), "the-secret")
    session = FakeSession()
    session.rows[(SessionRow, row.id)] = row

    await make_service(session).logout(f"{row.id}.the-secret")

    [statement] = session_updates(session)
    assert "revoked_at" in update_values(statement)
    # Conditional on the digest just checked, so a rotation in between wins.
    assert "token_hash" in str(statement.whereclause)


# The session id alone is not a secret; only the whole token ends a session.
async def test_logout_with_a_wrong_secret_revokes_nothing() -> None:
    row = make_session_row(make_user(), "the-secret")
    session = FakeSession()
    session.rows[(SessionRow, row.id)] = row
    revocations = RecordingRevocations()

    await AuthService(cast("AsyncSession", session), CONFIG, sessions=revocations).logout(
        f"{row.id}.guessed"
    )

    assert session_updates(session) == []
    assert revocations.sessions == []


async def test_logout_of_a_missing_session_costs_the_same_digest_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked: list[str] = []

    async def recording_verify(password: str, password_hash: str) -> bool:
        del password
        checked.append(password_hash)
        return False

    monkeypatch.setattr(auth_service_module, "verify_password_async", recording_verify)
    session = FakeSession()

    await make_service(session).logout(f"{uuid.uuid4()}.any")

    assert checked == [DUMMY_PASSWORD_HASH]
    assert session.statements == []


# A socket opened with the session is closed with it.
async def test_logout_reports_the_session_it_ended() -> None:
    row = make_session_row(make_user(), "the-secret")
    session = FakeSession()
    session.rows[(SessionRow, row.id)] = row
    revocations = RecordingRevocations()

    await AuthService(cast("AsyncSession", session), CONFIG, sessions=revocations).logout(
        f"{row.id}.the-secret"
    )

    assert revocations.sessions == [row.id]


async def test_logout_reports_nothing_when_a_refresh_rotated_the_secret_first() -> None:
    row = make_session_row(make_user(), "the-secret")
    session = FakeSession()
    session.rows[(SessionRow, row.id)] = row
    session.rowcount = 0
    revocations = RecordingRevocations()

    await AuthService(cast("AsyncSession", session), CONFIG, sessions=revocations).logout(
        f"{row.id}.the-secret"
    )

    assert revocations.sessions == []


async def test_an_access_token_reports_when_it_expires() -> None:
    user = make_user()
    row = make_session_row(user, "s")
    session = FakeSession(found_user=user)
    session.rows[(SessionRow, row.id)] = row
    session.rows[(User, user.id)] = user
    expiry = datetime.now(tz=UTC).replace(microsecond=0) + timedelta(minutes=15)

    token = jwt.encode(
        {"sub": str(user.id), "sessionId": str(row.id), "type": "access", "exp": expiry},
        CONFIG.access_token_secret,
        algorithm="HS256",
    )

    auth = await make_service(session).authenticate(token)

    assert auth.expires_at == expiry


async def test_an_access_token_without_an_expiry_is_refused() -> None:
    user = make_user()
    row = make_session_row(user, "s")
    session = FakeSession(found_user=user)
    session.rows[(SessionRow, row.id)] = row
    session.rows[(User, user.id)] = user

    token = jwt.encode(
        {"sub": str(user.id), "sessionId": str(row.id), "type": "access"},
        CONFIG.access_token_secret,
        algorithm="HS256",
    )

    with pytest.raises(UnauthorizedError):
        await make_service(session).authenticate(token)


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


# Bcrypt reads 72 bytes; a longer password is refused at the boundary.
@pytest.mark.parametrize("password", ["a" * 73, "ї" * 37])
def test_a_login_password_over_72_bytes_is_refused(password: str) -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="morgan@example.com", password=password)


# Bcrypt runs on a worker thread, never on the event loop.
async def test_hashing_and_verifying_run_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop_thread = threading.get_ident()
    threads: list[int] = []

    def recording_hash(password: str) -> str:
        threads.append(threading.get_ident())
        return f"digest-of-{password}"

    def recording_verify(password: str, password_hash: str) -> bool:
        threads.append(threading.get_ident())
        return password_hash == f"digest-of-{password}"

    monkeypatch.setattr(security, "hash_password", recording_hash)
    monkeypatch.setattr(security, "verify_password", recording_verify)

    digest = await hash_password_async("secret")
    assert await verify_password_async("secret", digest)

    assert len(threads) == 2
    assert loop_thread not in threads


# An unknown address costs a password check like any other failure.
async def test_an_unknown_address_is_checked_against_a_dummy_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked: list[str] = []

    async def recording_verify(password: str, password_hash: str) -> bool:
        del password
        checked.append(password_hash)
        return False

    monkeypatch.setattr(auth_service_module, "verify_password_async", recording_verify)

    with pytest.raises(UnauthorizedError):
        await make_service(FakeSession(found_user=None)).login(
            LoginRequest(email="nobody@example.com", password=PASSWORD)
        )

    assert checked == [DUMMY_PASSWORD_HASH]


async def test_a_disabled_account_is_checked_like_an_active_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked: list[str] = []

    async def recording_verify(password: str, password_hash: str) -> bool:
        del password
        checked.append(password_hash)
        return True

    monkeypatch.setattr(auth_service_module, "verify_password_async", recording_verify)

    with pytest.raises(UnauthorizedError):
        await make_service(FakeSession(found_user=make_user(is_active=False))).login(
            LoginRequest(email="morgan@example.com", password=PASSWORD)
        )

    assert checked == [PASSWORD_HASH]


def test_the_dummy_digest_costs_the_same_as_a_real_one() -> None:
    assert DUMMY_PASSWORD_HASH.startswith(f"$2b${BCRYPT_ROUNDS:02d}$")
    assert not verify_password(PASSWORD, DUMMY_PASSWORD_HASH)


# The session records where it was opened and last renewed from.
async def test_login_records_the_client_on_the_new_session() -> None:
    session = FakeSession(found_user=make_user())
    client = ClientInfo(ip_address="203.0.113.7", user_agent="probe/1.0")

    await make_service(session, client).login(
        LoginRequest(email="morgan@example.com", password=PASSWORD)
    )

    [row] = session.added
    assert row.ip_address == "203.0.113.7"
    assert row.user_agent == "probe/1.0"


async def test_refresh_records_the_client_on_the_renewed_session() -> None:
    user = make_user()
    row = make_session_row(user, "s")
    session = FakeSession(found_user=user)
    session.rows[(SessionRow, row.id)] = row
    client = ClientInfo(ip_address="198.51.100.2", user_agent="probe/2.0")

    await make_service(session, client).refresh(f"{row.id}.s")

    [rotation] = session_updates(session)
    values = update_values(rotation)
    assert values["ip_address"] == "198.51.100.2"
    assert values["user_agent"] == "probe/2.0"


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("::ffff:203.0.113.7", "203.0.113.7"),
        ("2001:db8::1", "2001:db8::1"),
        ("testclient", None),
        (None, None),
    ],
)
def test_the_client_address_is_stored_only_when_it_is_an_address(
    host: str | None, expected: str | None
) -> None:
    assert ClientInfo.of(host, None).ip_address == expected


def test_a_long_user_agent_is_cut_to_the_column_width() -> None:
    assert ClientInfo.of(None, "x" * 600).user_agent == "x" * 512
    assert ClientInfo.of(None, "").user_agent is None


def test_ended_sessions_are_reported_to_the_gateway_the_app_runs() -> None:
    listener = RecordingRevocations()
    with_gateway = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(realtime=listener)))
    without = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    assert get_session_revocations(cast("Request", with_gateway)) is listener
    assert isinstance(
        get_session_revocations(cast("Request", without)), NoopSessionRevocationListener
    )
