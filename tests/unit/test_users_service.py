"""User administration rules, and the guarantees around passwords."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.db.models.rbac import Role, UserRole
from app.db.models.user import Session as SessionRow
from app.db.models.user import User
from app.modules.users.schemas import CreateUserRequest, UpdateUserRequest
from app.modules.users.service import UsersService, to_session_out, to_user_out

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)


class FakeScalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def unique(self) -> FakeScalars:
        return self

    def all(self) -> list[Any]:
        return list(self._values)

    def one_or_none(self) -> Any:
        return self._values[0] if self._values else None


class FakeResult:
    def __init__(self, values: list[Any] | None = None) -> None:
        self._values = values or []

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._values)


class FakeSession:
    """A scripted stand-in: each call pops the next prepared answer."""

    def __init__(self) -> None:
        self.execute_queue: list[list[Any]] = []
        self.scalar_queue: list[Any] = []
        self.rows: dict[Any, Any] = {}
        self.added: list[Any] = []
        self.statements: list[Any] = []
        self.flushes = 0

    async def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.execute_queue.pop(0) if self.execute_queue else [])

    async def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        return self.scalar_queue.pop(0) if self.scalar_queue else None

    async def get(self, model: Any, primary_key: Any) -> Any:
        return self.rows.get((model, primary_key))

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushes += 1


class RecordingInvalidator:
    def __init__(self) -> None:
        self.invalidated: list[uuid.UUID] = []

    async def invalidate_user_permissions(self, user_id: Any) -> None:
        self.invalidated.append(user_id)


def make_user(*, is_active: bool = True) -> User:
    role = Role(id=uuid.uuid4(), name="manager")
    return User(
        id=uuid.uuid4(),
        email="morgan@example.com",
        name="Morgan Manager",
        password_hash="never-leaves-the-database",
        is_active=is_active,
        created_at=NOW,
        updated_at=NOW,
        user_roles=[UserRole(role=role)],
    )


def test_the_public_shape_of_a_user_has_no_password_field() -> None:
    user = make_user()

    payload = to_user_out(user).model_dump(by_alias=True)

    assert "password" not in payload
    assert "passwordHash" not in payload
    assert payload["roles"] == [{"id": user.user_roles[0].role.id, "name": "manager"}]
    assert payload["isActive"] is True


def test_the_public_shape_of_a_session_has_no_token_digest() -> None:
    row = SessionRow(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash="digest-that-must-not-travel",
        expires_at=NOW + timedelta(days=7),
        revoked_at=None,
        ip_address="203.0.113.7",
        user_agent="probe/1.0",
        created_at=NOW,
        updated_at=NOW,
    )

    payload = to_session_out(row).model_dump(by_alias=True)

    assert "tokenHash" not in payload
    assert payload["revokedAt"] is None
    assert payload["ipAddress"] == "203.0.113.7"


def test_a_patch_with_no_fields_is_rejected() -> None:
    with pytest.raises(ValidationError):
        UpdateUserRequest()


def test_a_patch_distinguishes_an_absent_field_from_a_given_one() -> None:
    payload = UpdateUserRequest.model_validate({"name": "Morgan"})

    # Only `name` was sent, so nothing else may be written.
    assert payload.model_fields_set == {"name"}
    assert payload.email is None


def test_an_address_is_folded_before_it_is_stored() -> None:
    payload = CreateUserRequest.model_validate(
        {
            "email": " Morgan@Example.COM ",
            "name": "Morgan",
            "password": "correct-horse",
            "roleIds": [str(uuid.uuid4())],
        }
    )

    assert payload.email == "morgan@example.com"


async def test_creating_a_user_with_a_taken_address_is_a_conflict() -> None:
    session = FakeSession()
    session.scalar_queue = [uuid.uuid4()]  # the address is already in use
    service = UsersService(cast("AsyncSession", session))

    with pytest.raises(ConflictError) as error:
        await service.create(
            CreateUserRequest.model_validate(
                {
                    "email": "morgan@example.com",
                    "name": "Morgan",
                    "password": "correct-horse",
                    "roleIds": [str(uuid.uuid4())],
                }
            )
        )

    assert error.value.code == "EMAIL_ALREADY_EXISTS"
    assert session.added == []


async def test_creating_a_user_with_an_unknown_role_is_a_not_found() -> None:
    session = FakeSession()
    session.scalar_queue = [None]  # the address is free
    session.execute_queue = [[]]  # no matching roles
    service = UsersService(cast("AsyncSession", session))

    with pytest.raises(NotFoundError) as error:
        await service.create(
            CreateUserRequest.model_validate(
                {
                    "email": "morgan@example.com",
                    "name": "Morgan",
                    "password": "correct-horse",
                    "roleIds": [str(uuid.uuid4())],
                }
            )
        )

    assert error.value.code == "USER_OR_ROLE_NOT_FOUND"


async def test_a_new_password_is_stored_only_as_a_digest() -> None:
    user = make_user()
    session = FakeSession()
    session.execute_queue = [[user], [user]]
    service = UsersService(cast("AsyncSession", session))

    await service.update(user.id, UpdateUserRequest.model_validate({"password": "new-password"}))

    assert user.password_hash != "new-password"
    assert user.password_hash.startswith("$2")


async def test_changing_roles_forgets_the_cached_permissions_of_that_user() -> None:
    user = make_user()
    role_id = uuid.uuid4()
    session = FakeSession()
    session.execute_queue = [[user], [role_id], [], [user]]
    invalidator = RecordingInvalidator()
    service = UsersService(cast("AsyncSession", session), invalidator)

    await service.update(user.id, UpdateUserRequest.model_validate({"roleIds": [str(role_id)]}))

    assert invalidator.invalidated == [user.id]
    assert [row.role_id for row in session.added if isinstance(row, UserRole)] == [role_id]


async def test_disabling_an_account_also_ends_its_live_sessions() -> None:
    user = make_user()
    session = FakeSession()
    session.execute_queue = [[user], [], [user]]
    invalidator = RecordingInvalidator()
    service = UsersService(cast("AsyncSession", session), invalidator)

    await service.disable(user.id)

    assert user.is_active is False
    # A refresh token outliving the account would keep minting access tokens.
    assert len(session.statements) >= 2
    assert invalidator.invalidated == [user.id]


async def test_addressing_a_session_of_another_account_is_a_not_found() -> None:
    user = make_user()
    other_row = SessionRow(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash="digest",
        expires_at=NOW + timedelta(days=7),
    )
    session = FakeSession()
    session.scalar_queue = [user.id]
    session.rows[(SessionRow, other_row.id)] = other_row
    service = UsersService(cast("AsyncSession", session))

    with pytest.raises(NotFoundError) as error:
        await service.revoke_session(user.id, other_row.id)

    assert error.value.code == "SESSION_NOT_FOUND"


async def test_revoking_an_already_revoked_session_succeeds() -> None:
    user = make_user()
    revoked_at = NOW - timedelta(hours=1)
    row = SessionRow(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash="digest",
        expires_at=NOW + timedelta(days=7),
        revoked_at=revoked_at,
    )
    session = FakeSession()
    session.scalar_queue = [user.id]
    session.rows[(SessionRow, row.id)] = row
    service = UsersService(cast("AsyncSession", session))

    await service.revoke_session(user.id, row.id)

    # The caller asked for a state that already holds; the timestamp is not
    # rewritten.
    assert row.revoked_at == revoked_at


async def test_listing_sessions_of_an_unknown_user_is_a_not_found() -> None:
    session = FakeSession()
    session.scalar_queue = [None]
    service = UsersService(cast("AsyncSession", session))

    with pytest.raises(NotFoundError) as error:
        await service.list_sessions(uuid.uuid4())

    assert error.value.code == "USER_NOT_FOUND"


async def test_a_page_reports_the_total_alongside_its_slice() -> None:
    user = make_user()
    session = FakeSession()
    session.scalar_queue = [7]
    session.execute_queue = [[user]]
    service = UsersService(cast("AsyncSession", session))

    items, total = await service.list_users(2, 20)

    assert total == 7
    assert [item.id for item in items] == [user.id]
