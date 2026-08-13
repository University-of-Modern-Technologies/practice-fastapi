"""Authorization rules and the permission cache around them."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.db.enums import PermissionScope
from app.db.models.rbac import Permission, Role, RolePermission, UserRole
from app.db.models.user import User
from app.modules.auth.types import AuthContext
from app.modules.rbac.dependencies import ensure_scope_all, ensure_scope_covers
from app.modules.rbac.service import RbacService
from app.modules.rbac.types import (
    CachedUserPermissions,
    NoopCache,
    create_permission_key,
    parse_permission_key,
    user_permissions_key,
    user_permissions_prefix,
)


class FakeResult:
    def __init__(self, value: Any = None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    def __init__(self, *, found_user: User | None = None) -> None:
        self.found_user = found_user
        self.queries = 0

    async def execute(self, statement: Any) -> FakeResult:  # noqa: ARG002
        self.queries += 1
        return FakeResult(self.found_user)


class FakeCache:
    """An in-memory stand-in that records what was invalidated."""

    def __init__(self) -> None:
        self.entries: dict[str, Any] = {}
        self.deleted: list[str] = []
        self.prefixes: list[str] = []

    async def get(self, key: str) -> Any | None:
        return self.entries.get(key)

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        self.entries[key] = value
        self.ttl_seconds = ttl_seconds

    async def remember[T](
        self,
        key: str,
        ttl_seconds: int,
        loader: Callable[[], Awaitable[T]],
    ) -> T:
        cached = self.entries.get(key)
        if cached is not None:
            return cast("T", cached)
        value = await loader()
        await self.set(key, value, ttl_seconds)
        return value

    async def delete(self, keys: str | Sequence[str]) -> None:
        for key in [keys] if isinstance(keys, str) else list(keys):
            self.deleted.append(key)
            self.entries.pop(key, None)

    async def invalidate_prefix(self, prefix: str) -> None:
        self.prefixes.append(prefix)
        for key in [key for key in self.entries if key.startswith(prefix)]:
            del self.entries[key]


def make_user(grants: list[tuple[str, PermissionScope]], *, is_active: bool = True) -> User:
    role = Role(
        id=uuid.uuid4(),
        name="manager",
        permissions=[
            RolePermission(scope=scope, permission=Permission(id=uuid.uuid4(), key=key))
            for key, scope in grants
        ],
    )
    return User(
        id=uuid.uuid4(),
        email="morgan@example.com",
        name="Morgan Manager",
        password_hash="hash",
        is_active=is_active,
        user_roles=[UserRole(role=role)],
    )


def make_service(session: FakeSession, cache: FakeCache | None = None) -> RbacService:
    return RbacService(cast("AsyncSession", session), cache)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("contacts:read", ("contacts", "read")),
        ("a:b", ("a", "b")),
    ],
)
def test_a_well_formed_key_splits_into_two_halves(key: str, expected: tuple[str, str]) -> None:
    assert parse_permission_key(key) == expected


@pytest.mark.parametrize("key", ["", ":", "contacts", ":read", "contacts:", "a:b:c"])
def test_anything_but_exactly_one_separator_is_not_a_permission_key(key: str) -> None:
    assert parse_permission_key(key) is None


def test_the_two_key_functions_are_inverses() -> None:
    assert parse_permission_key(create_permission_key("orders", "write")) == ("orders", "write")


def test_the_cache_namespace_prefix_ends_with_the_separator() -> None:
    # Without the trailing separator the prefix would also match a namespace
    # that merely starts with the same letters.
    assert user_permissions_prefix().endswith(":")
    assert user_permissions_key("abc").startswith(user_permissions_prefix())


async def test_the_no_op_cache_never_reports_a_hit() -> None:
    cache = NoopCache()

    await cache.set("key", {"a": 1}, 60)

    assert await cache.get("key") is None


def test_a_snapshot_survives_a_round_trip_through_the_cache() -> None:
    snapshot = CachedUserPermissions(is_active=True, scopes={"contacts:read": PermissionScope.ALL})

    restored = CachedUserPermissions.from_payload(snapshot.to_payload())

    assert restored == snapshot


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "text",
        {},
        {"isActive": True},
        {"isActive": 1, "scopes": {}},
        {"isActive": True, "scopes": {"contacts:read": "EVERYTHING"}},
    ],
)
def test_an_unrecognised_cache_entry_is_treated_as_a_miss(payload: Any) -> None:
    assert CachedUserPermissions.from_payload(payload) is None


async def test_the_widest_grant_wins_across_roles() -> None:
    user = make_user(
        [("contacts:read", PermissionScope.OWN), ("contacts:read", PermissionScope.ALL)]
    )
    service = make_service(FakeSession(found_user=user))

    assert await service.get_permission_scope(user.id, "contacts", "read") == PermissionScope.ALL


async def test_a_permission_that_was_never_granted_resolves_to_nothing() -> None:
    user = make_user([("contacts:read", PermissionScope.ALL)])
    service = make_service(FakeSession(found_user=user))

    assert await service.get_permission_scope(user.id, "contacts", "delete") is None


async def test_a_disabled_account_holds_no_permissions_at_all() -> None:
    user = make_user([("contacts:read", PermissionScope.ALL)], is_active=False)
    service = make_service(FakeSession(found_user=user))

    assert await service.get_permission_scope(user.id, "contacts", "read") is None


async def test_an_unknown_user_holds_no_permissions() -> None:
    service = make_service(FakeSession(found_user=None))

    assert await service.get_permission_scope(uuid.uuid4(), "contacts", "read") is None


async def test_the_snapshot_is_read_once_and_then_served_from_the_cache() -> None:
    user = make_user([("contacts:read", PermissionScope.ALL)])
    session = FakeSession(found_user=user)
    cache = FakeCache()
    service = make_service(session, cache)

    await service.get_permission_scope(user.id, "contacts", "read")
    await service.get_permission_scope(user.id, "contacts", "read")

    assert session.queries == 1
    assert user_permissions_key(str(user.id)) in cache.entries


async def test_changing_one_user_drops_only_that_user_s_snapshot() -> None:
    cache = FakeCache()
    user_id = uuid.uuid4()
    other_id = uuid.uuid4()
    cache.entries[user_permissions_key(str(user_id))] = {"isActive": True, "scopes": {}}
    cache.entries[user_permissions_key(str(other_id))] = {"isActive": True, "scopes": {}}

    await make_service(FakeSession(), cache).invalidate_user_permissions(user_id)

    assert cache.deleted == [user_permissions_key(str(user_id))]
    assert user_permissions_key(str(other_id)) in cache.entries


async def test_changing_a_role_drops_every_snapshot() -> None:
    cache = FakeCache()
    cache.entries[user_permissions_key(str(uuid.uuid4()))] = {"isActive": True, "scopes": {}}

    await make_service(FakeSession(), cache).invalidate_all_user_permissions()

    # The cache holds no reverse mapping from a role to its holders, so the
    # whole namespace goes.
    assert cache.prefixes == [user_permissions_prefix()]
    assert cache.entries == {}


def test_a_collection_endpoint_rejects_an_owner_only_grant() -> None:
    with pytest.raises(ForbiddenError):
        ensure_scope_all(PermissionScope.OWN)

    ensure_scope_all(PermissionScope.ALL)


def test_an_owner_only_grant_reaches_its_own_record_and_no_other() -> None:
    auth = AuthContext(user_id=uuid.uuid4(), session_id=uuid.uuid4())

    ensure_scope_covers(PermissionScope.OWN, auth, auth.user_id)
    ensure_scope_covers(PermissionScope.ALL, auth, uuid.uuid4())

    with pytest.raises(ForbiddenError):
        ensure_scope_covers(PermissionScope.OWN, auth, uuid.uuid4())
