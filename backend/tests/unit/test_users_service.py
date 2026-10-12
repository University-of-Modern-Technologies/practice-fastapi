"""User administration rules, and the guarantees around passwords."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy import Delete, Select, Update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.db.models.rbac import Role, UserRole
from app.db.models.user import Session as SessionRow
from app.db.models.user import User
from app.modules.audit import AuditEvent, AuditService
from app.modules.rbac.types import Actor
from app.modules.users.schemas import CreateUserRequest, UpdateUserRequest
from app.modules.users.service import UsersService, to_session_out, to_user_out

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)
ACTOR = Actor(actor_id=uuid.UUID("10000000-0000-4000-8000-000000000001"), ip_address="203.0.113.7")


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

    async def refresh(self, instance: Any) -> None:
        if getattr(instance, "updated_at", None) is None:
            instance.updated_at = NOW
        if getattr(instance, "created_at", None) is None:
            instance.created_at = NOW


class RecordingAudit:
    """Keeps what would have been written to the trail."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def make_service(
    session: FakeSession,
    invalidator: RecordingInvalidator | None = None,
    audit: RecordingAudit | None = None,
) -> UsersService:
    return UsersService(
        cast("AsyncSession", session),
        invalidator,
        cast("AuditService", audit if audit is not None else RecordingAudit()),
    )


class RecordingInvalidator:
    def __init__(self) -> None:
        self.invalidated: list[uuid.UUID] = []

    async def invalidate_user_permissions(self, user_id: Any) -> None:
        self.invalidated.append(user_id)


def make_user(*, is_active: bool = True, role_name: str = "manager") -> User:
    role = Role(id=uuid.uuid4(), name=role_name)
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
    service = make_service(session)

    with pytest.raises(ConflictError) as error:
        await service.create(
            ACTOR,
            CreateUserRequest.model_validate(
                {
                    "email": "morgan@example.com",
                    "name": "Morgan",
                    "password": "correct-horse",
                    "roleIds": [str(uuid.uuid4())],
                }
            ),
        )

    assert error.value.code == "EMAIL_ALREADY_EXISTS"
    assert session.added == []


async def test_creating_a_user_with_an_unknown_role_is_a_not_found() -> None:
    session = FakeSession()
    session.scalar_queue = [None]  # the address is free
    session.execute_queue = [[]]  # no matching roles
    service = make_service(session)

    with pytest.raises(NotFoundError) as error:
        await service.create(
            ACTOR,
            CreateUserRequest.model_validate(
                {
                    "email": "morgan@example.com",
                    "name": "Morgan",
                    "password": "correct-horse",
                    "roleIds": [str(uuid.uuid4())],
                }
            ),
        )

    assert error.value.code == "USER_OR_ROLE_NOT_FOUND"


async def test_a_new_password_is_stored_only_as_a_digest() -> None:
    user = make_user()
    session = FakeSession()
    session.execute_queue = [[user], [], [user]]
    service = make_service(session)

    await service.update(
        ACTOR, user.id, UpdateUserRequest.model_validate({"password": "new-password"})
    )

    assert user.password_hash != "new-password"
    assert user.password_hash.startswith("$2")


async def test_changing_roles_forgets_the_cached_permissions_of_that_user() -> None:
    user = make_user()
    role_id = uuid.uuid4()
    session = FakeSession()
    session.execute_queue = [[user], [role_id], [], [user]]
    invalidator = RecordingInvalidator()
    service = make_service(session, invalidator)

    await service.update(
        ACTOR, user.id, UpdateUserRequest.model_validate({"roleIds": [str(role_id)]})
    )

    assert invalidator.invalidated == [user.id]
    assert [row.role_id for row in session.added if isinstance(row, UserRole)] == [role_id]


async def test_disabling_an_account_also_ends_its_live_sessions() -> None:
    user = make_user()
    session = FakeSession()
    session.execute_queue = [[user], [], [user]]
    invalidator = RecordingInvalidator()
    service = make_service(session, invalidator)

    await service.disable(ACTOR, user.id)

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
    service = make_service(session)

    with pytest.raises(NotFoundError) as error:
        await service.revoke_session(ACTOR, user.id, other_row.id)

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
    service = make_service(session)

    await service.revoke_session(ACTOR, user.id, row.id)

    # The caller asked for a state that already holds; the timestamp is not
    # rewritten.
    assert row.revoked_at == revoked_at


async def test_listing_sessions_of_an_unknown_user_is_a_not_found() -> None:
    session = FakeSession()
    session.scalar_queue = [None]
    service = make_service(session)

    with pytest.raises(NotFoundError) as error:
        await service.list_sessions(uuid.uuid4())

    assert error.value.code == "USER_NOT_FOUND"


async def test_a_page_reports_the_total_alongside_its_slice() -> None:
    user = make_user()
    session = FakeSession()
    session.scalar_queue = [7]
    session.execute_queue = [[user]]
    service = make_service(session)

    items, total = await service.list_users(2, 20)

    assert total == 7
    assert [item.id for item in items] == [user.id]


def _payload(**overrides: Any) -> dict[str, Any]:
    return {
        "email": "morgan@example.com",
        "name": "Morgan",
        "password": "correct-horse",
        "roleIds": [str(uuid.uuid4())],
        **overrides,
    }


# Bcrypt reads 72 bytes; a longer password is refused, never truncated.
@pytest.mark.parametrize(
    "password",
    ["a" * 73, "ї" * 37],
    ids=["ascii-over-72-bytes", "cyrillic-under-72-characters-over-72-bytes"],
)
def test_a_password_over_72_bytes_is_refused_on_create_and_update(password: str) -> None:
    with pytest.raises(ValidationError):
        CreateUserRequest.model_validate(_payload(password=password))
    with pytest.raises(ValidationError):
        UpdateUserRequest.model_validate({"password": password})


def test_a_password_of_exactly_72_bytes_is_accepted() -> None:
    assert CreateUserRequest.model_validate(_payload(password="a" * 72)).password == "a" * 72


# Names are trimmed before their length is checked, as the sibling does.
def test_a_user_name_is_trimmed_and_a_blank_one_refused() -> None:
    assert CreateUserRequest.model_validate(_payload(name="  Morgan  ")).name == "Morgan"
    with pytest.raises(ValidationError):
        UpdateUserRequest.model_validate({"name": "   "})


# A new password ends every session opened with the old one.
async def test_changing_the_password_revokes_the_live_sessions_of_that_user() -> None:
    user = make_user()
    session = FakeSession()
    session.execute_queue = [[user], [], [user]]

    await make_service(session).update(
        ACTOR, user.id, UpdateUserRequest.model_validate({"password": "new-password"})
    )

    revocations = [
        statement
        for statement in session.statements
        if isinstance(statement, Update) and getattr(statement.table, "name", None) == "sessions"
    ]
    assert len(revocations) == 1
    where = str(revocations[0].whereclause)
    assert "sessions.user_id" in where
    assert "sessions.revoked_at IS NULL" in where


async def test_a_change_without_a_new_password_keeps_the_sessions() -> None:
    user = make_user()
    session = FakeSession()
    session.execute_queue = [[user], [user]]

    await make_service(session).update(
        ACTOR, user.id, UpdateUserRequest.model_validate({"name": "Morgan"})
    )

    assert not any(isinstance(statement, Update) for statement in session.statements)


# The answer to a PATCH is read past the identity map, so new roles show.
async def test_the_user_returned_by_an_update_is_reloaded_rather_than_reused() -> None:
    user = make_user()
    role_id = uuid.uuid4()
    session = FakeSession()
    session.execute_queue = [[user], [role_id], [], [user]]

    await make_service(session).update(
        ACTOR, user.id, UpdateUserRequest.model_validate({"roleIds": [str(role_id)]})
    )

    final_read = session.statements[-1]
    assert isinstance(final_read, Select)
    assert final_read.get_execution_options().get("populate_existing") is True


# Repeated role ids collapse into one assignment.
async def test_repeated_role_ids_are_assigned_once() -> None:
    role_id = uuid.uuid4()
    created = make_user()
    session = FakeSession()
    session.scalar_queue = [None]
    session.execute_queue = [[role_id], [created]]

    await make_service(session).create(
        ACTOR, CreateUserRequest.model_validate(_payload(roleIds=[str(role_id)] * 3))
    )

    assert [row.role_id for row in session.added if isinstance(row, UserRole)] == [role_id]


# An administrator cannot lock administrators out.
async def test_disabling_your_own_account_is_a_conflict() -> None:
    user = make_user()
    session = FakeSession()
    session.execute_queue = [[user]]

    with pytest.raises(ConflictError) as error:
        await make_service(session).disable(Actor(actor_id=user.id), user.id)

    assert error.value.code == "CANNOT_DISABLE_SELF"
    assert user.is_active is True


async def test_disabling_the_last_active_admin_is_a_conflict() -> None:
    admin = make_user(role_name="admin")
    session = FakeSession()
    session.execute_queue = [[admin]]
    session.scalar_queue = [uuid.uuid4(), 0]  # the locked admin role, no other holder

    with pytest.raises(ConflictError) as error:
        await make_service(session).disable(ACTOR, admin.id)

    assert error.value.code == "LAST_ACTIVE_ADMIN"
    assert admin.is_active is True
    lock = session.statements[1]
    assert isinstance(lock, Select)
    assert lock._for_update_arg is not None


async def test_an_admin_can_be_disabled_while_another_one_is_active() -> None:
    admin = make_user(role_name="admin")
    session = FakeSession()
    session.execute_queue = [[admin], [], [admin]]
    session.scalar_queue = [uuid.uuid4(), 1]

    await make_service(session).disable(ACTOR, admin.id)

    assert admin.is_active is False


async def test_taking_the_admin_role_from_its_last_active_holder_is_a_conflict() -> None:
    admin = make_user(role_name="admin")
    other_role = uuid.uuid4()
    session = FakeSession()
    session.execute_queue = [[admin], [other_role]]
    session.scalar_queue = [uuid.uuid4(), 0]

    with pytest.raises(ConflictError) as error:
        await make_service(session).update(
            ACTOR, admin.id, UpdateUserRequest.model_validate({"roleIds": [str(other_role)]})
        )

    assert error.value.code == "LAST_ACTIVE_ADMIN"
    assert not any(isinstance(statement, Delete) for statement in session.statements)


async def test_keeping_the_admin_role_needs_no_other_admin() -> None:
    admin = make_user(role_name="admin")
    admin_role_id = uuid.uuid4()
    session = FakeSession()
    session.execute_queue = [[admin], [admin_role_id], [], [admin]]
    session.scalar_queue = [admin_role_id]

    await make_service(session).update(
        ACTOR, admin.id, UpdateUserRequest.model_validate({"roleIds": [str(admin_role_id)]})
    )

    assert session.scalar_queue == []


# Every change to an account lands in the trail, attributed to the caller.
async def test_creating_a_user_is_audited() -> None:
    created = make_user()
    session = FakeSession()
    session.scalar_queue = [None]
    role_id = uuid.uuid4()
    session.execute_queue = [[role_id], [created]]
    audit = RecordingAudit()

    await make_service(session, audit=audit).create(
        ACTOR, CreateUserRequest.model_validate(_payload(roleIds=[str(role_id)]))
    )

    [event] = audit.events
    assert event.action == "user.created"
    assert event.entity_type == "user"
    assert event.actor_id == ACTOR.actor_id
    assert event.ip_address == ACTOR.ip_address
    assert event.changes["after"]["email"] == created.email
    assert "password" not in str(event.changes)


async def test_updating_a_user_is_audited_with_the_changed_field_names() -> None:
    user = make_user()
    session = FakeSession()
    session.execute_queue = [[user], [], [user]]
    audit = RecordingAudit()

    await make_service(session, audit=audit).update(
        ACTOR,
        user.id,
        UpdateUserRequest.model_validate({"password": "new-password", "name": "Morgan"}),
    )

    [event] = audit.events
    assert event.action == "user.updated"
    assert event.entity_id == user.id
    assert set(event.changes) == {"before", "after"}
    assert event.metadata == {"changedFields": ["name", "password"]}


async def test_disabling_a_user_is_audited() -> None:
    user = make_user()
    session = FakeSession()
    session.execute_queue = [[user], [], [user]]
    audit = RecordingAudit()

    await make_service(session, audit=audit).disable(ACTOR, user.id)

    [event] = audit.events
    assert event.action == "user.disabled"
    assert event.changes["before"]["isActive"] is True
    assert event.changes["after"]["isActive"] is False


async def test_revoking_a_live_session_is_audited() -> None:
    user = make_user()
    row = SessionRow(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash="digest",
        expires_at=NOW + timedelta(days=7),
        revoked_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    session = FakeSession()
    session.scalar_queue = [user.id]
    session.rows[(SessionRow, row.id)] = row
    audit = RecordingAudit()

    await make_service(session, audit=audit).revoke_session(ACTOR, user.id, row.id)

    [event] = audit.events
    assert event.action == "session.revoked"
    assert event.entity_type == "session"
    assert event.entity_id == row.id
    assert event.changes["before"]["revokedAt"] is None
    assert event.changes["after"]["revokedAt"] is not None
    assert "tokenHash" not in event.changes["after"]
    assert event.metadata == {"userId": user.id}


async def test_revoking_an_already_revoked_session_writes_nothing_to_the_trail() -> None:
    user = make_user()
    row = SessionRow(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash="digest",
        expires_at=NOW + timedelta(days=7),
        revoked_at=NOW,
    )
    session = FakeSession()
    session.scalar_queue = [user.id]
    session.rows[(SessionRow, row.id)] = row
    audit = RecordingAudit()

    await make_service(session, audit=audit).revoke_session(ACTOR, user.id, row.id)

    assert audit.events == []
