"""Role administration: what a role request accepts, and what it leaves behind."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.util import greenlet_spawn

from app.db.enums import PermissionScope
from app.db.models.rbac import Permission, Role, RolePermission
from app.modules.audit import AuditEvent, AuditService
from app.modules.rbac.schemas import CreateRoleRequest, ReplaceRolePermissionsRequest
from app.modules.rbac.service import RbacService
from app.modules.rbac.types import Actor, CachePort, user_permissions_prefix

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)
ACTOR = Actor(actor_id=uuid.UUID("10000000-0000-4000-8000-000000000001"), ip_address="203.0.113.7")
PERMISSION_ID = uuid.uuid4()


class FakeResult:
    """Answers whichever accessor the service happens to call."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def tuples(self) -> FakeResult:
        return self

    def all(self) -> Any:
        return self._value

    def scalars(self) -> FakeResult:
        return self

    def unique(self) -> FakeResult:
        return self

    def one_or_none(self) -> Any:
        return self._value


class FakeSession:
    def __init__(self) -> None:
        self.execute_queue: list[Any] = []
        self.rows: dict[Any, Any] = {}
        self.added: list[Any] = []
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.execute_queue.pop(0) if self.execute_queue else None)

    async def get(self, model: Any, primary_key: Any) -> Any:
        return self.rows.get((model, primary_key))

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        return None


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def make_role(scope: PermissionScope, *, role_id: uuid.UUID | None = None) -> Role:
    return Role(
        id=role_id or uuid.uuid4(),
        name="support",
        description="Support team",
        created_at=NOW,
        updated_at=NOW,
        permissions=[
            RolePermission(
                scope=scope, permission=Permission(id=PERMISSION_ID, key="contacts:read")
            )
        ],
    )


def make_service(session: FakeSession, audit: RecordingAudit) -> RbacService:
    return RbacService(cast("AsyncSession", session), audit=cast("AuditService", audit))


# Role names are trimmed, as the sibling does.
def test_a_role_name_and_description_are_trimmed() -> None:
    request = CreateRoleRequest.model_validate(
        {
            "name": "  support  ",
            "description": " Support team ",
            "permissions": [{"resource": " contacts ", "action": "read", "scope": "ALL"}],
        }
    )

    assert request.name == "support"
    assert request.description == "Support team"
    assert request.permissions[0].resource == "contacts"


@pytest.mark.parametrize("field", ["name", "description"])
def test_a_blank_role_name_or_description_is_refused(field: str) -> None:
    payload: dict[str, Any] = {"name": "support", "permissions": [], field: "   "}

    with pytest.raises(ValueError, match="at least 1 character"):
        CreateRoleRequest.model_validate(payload)


# Role administration lands in the trail, attributed to the caller.
async def test_creating_a_role_is_audited() -> None:
    session = FakeSession()
    created = make_role(PermissionScope.ALL)
    session.execute_queue = [None, [("contacts:read", PERMISSION_ID)], created]
    audit = RecordingAudit()

    await make_service(session, audit).create_role(
        ACTOR,
        CreateRoleRequest.model_validate(
            {
                "name": "support",
                "permissions": [{"resource": "contacts", "action": "read", "scope": "ALL"}],
            }
        ),
    )

    [event] = audit.events
    assert event.action == "role.created"
    assert event.entity_type == "role"
    assert event.actor_id == ACTOR.actor_id
    assert event.ip_address == ACTOR.ip_address
    assert event.changes["after"]["permissions"] == [
        {"resource": "contacts", "action": "read", "scope": "ALL"}
    ]


async def test_replacing_the_permissions_of_a_role_is_audited_before_and_after() -> None:
    role_id = uuid.uuid4()
    session = FakeSession()
    session.rows[(Role, role_id)] = Role(id=role_id, name="support")
    session.execute_queue = [
        [("contacts:read", PERMISSION_ID)],
        make_role(PermissionScope.ALL, role_id=role_id),
        None,
        make_role(PermissionScope.OWN, role_id=role_id),
    ]
    audit = RecordingAudit()

    replaced = await make_service(session, audit).replace_role_permissions(
        ACTOR,
        role_id,
        ReplaceRolePermissionsRequest.model_validate(
            {"permissions": [{"resource": "contacts", "action": "read", "scope": "OWN"}]}
        ),
    )

    assert replaced.permissions[0].scope == PermissionScope.OWN
    [event] = audit.events
    assert event.action == "role.permissions_replaced"
    assert event.entity_id == role_id
    assert event.changes["before"]["permissions"][0]["scope"] == "ALL"
    assert event.changes["after"]["permissions"][0]["scope"] == "OWN"


async def test_the_role_returned_after_a_replacement_is_reloaded_rather_than_reused() -> None:
    role_id = uuid.uuid4()
    session = FakeSession()
    session.rows[(Role, role_id)] = Role(id=role_id, name="support")
    session.execute_queue = [
        [("contacts:read", PERMISSION_ID)],
        make_role(PermissionScope.ALL, role_id=role_id),
        None,
        make_role(PermissionScope.OWN, role_id=role_id),
    ]

    await make_service(session, RecordingAudit()).replace_role_permissions(
        ACTOR,
        role_id,
        ReplaceRolePermissionsRequest.model_validate(
            {"permissions": [{"resource": "contacts", "action": "read", "scope": "OWN"}]}
        ),
    )

    final_read = session.statements[-1]
    assert isinstance(final_read, Select)
    assert final_read.get_execution_options().get("populate_existing") is True


class CommittingSession(FakeSession):
    """The scripted session, with a real transaction whose commit can be awaited."""

    def __init__(self) -> None:
        super().__init__()
        self.sync_session = Session()
        self.sync_session.begin()

    async def commit(self) -> None:
        await greenlet_spawn(self.sync_session.commit)


class RecordingCache:
    def __init__(self) -> None:
        self.dropped_prefixes: list[str] = []

    async def get(self, key: str) -> Any:
        del key

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        del key, value, ttl_seconds

    async def delete(self, keys: str | list[str]) -> None:
        del keys

    async def invalidate_prefix(self, prefix: str) -> None:
        self.dropped_prefixes.append(prefix)


# Dropped before the commit, a snapshot could be rebuilt from
# the old grants by a concurrent request and served for the whole TTL.
async def test_snapshots_are_dropped_only_once_a_role_change_commits() -> None:
    role_id = uuid.uuid4()
    session = CommittingSession()
    session.rows[(Role, role_id)] = Role(id=role_id, name="support")
    session.execute_queue = [
        [("contacts:read", PERMISSION_ID)],
        make_role(PermissionScope.ALL, role_id=role_id),
        None,
        make_role(PermissionScope.OWN, role_id=role_id),
    ]
    cache = RecordingCache()
    service = RbacService(
        cast("AsyncSession", session),
        cast("CachePort", cache),
        audit=cast("AuditService", RecordingAudit()),
    )

    await service.replace_role_permissions(
        ACTOR,
        role_id,
        ReplaceRolePermissionsRequest.model_validate(
            {"permissions": [{"resource": "contacts", "action": "read", "scope": "OWN"}]}
        ),
    )
    assert cache.dropped_prefixes == []

    await session.commit()
    assert cache.dropped_prefixes == [user_permissions_prefix()]
