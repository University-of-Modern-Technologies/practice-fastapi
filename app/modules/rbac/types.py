"""Vocabulary of the authorization module.

A permission is stored as a single ``resource:action`` string but is reasoned
about as two parts, so the two conversions live here and nowhere else. The cache
is described as a protocol rather than imported, which keeps authorization
independent of whether a cache backend is wired in at all.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol

from app.db.enums import PermissionScope

__all__ = [
    "CachePort",
    "CachedUserPermissions",
    "NoopCache",
    "PermissionKeyParts",
    "PermissionScope",
    "UserPermissionsInvalidator",
    "create_permission_key",
    "parse_permission_key",
    "user_permissions_key",
    "user_permissions_prefix",
]

KEY_SEPARATOR = ":"

#: Cache namespace of the permission snapshots, so the whole set can be dropped
#: with one prefix scan when a role changes.
RBAC_NAMESPACE = "rbac"
USER_PERMISSIONS_NAMESPACE = "user-permissions"

DEFAULT_PERMISSIONS_TTL_SECONDS = 300


class PermissionKeyParts(NamedTuple):
    """The two halves of a permission key."""

    resource: str
    action: str


def create_permission_key(resource: str, action: str) -> str:
    """Joins a resource and an action into the stored key."""
    return f"{resource}{KEY_SEPARATOR}{action}"


def parse_permission_key(key: str) -> PermissionKeyParts | None:
    """Splits a stored key, or returns ``None`` when it is not one.

    Exactly one separator is required: a key with none, with an empty half or
    with a second colon is not a permission this system can act on, and reading
    it as one would silently grant something nobody wrote.
    """
    separator = key.find(KEY_SEPARATOR)
    if separator < 1 or separator == len(key) - 1:
        return None
    if key.find(KEY_SEPARATOR, separator + 1) != -1:
        return None
    return PermissionKeyParts(resource=key[:separator], action=key[separator + 1 :])


def user_permissions_key(user_id: str) -> str:
    """Cache key holding one user's whole permission snapshot."""
    return KEY_SEPARATOR.join((RBAC_NAMESPACE, USER_PERMISSIONS_NAMESPACE, user_id))


def user_permissions_prefix() -> str:
    """Prefix covering every user's snapshot.

    It ends with the separator so that ``rbac:user-permissions`` never also
    matches a neighbouring namespace that merely starts with the same letters.
    """
    return f"{KEY_SEPARATOR.join((RBAC_NAMESPACE, USER_PERMISSIONS_NAMESPACE))}{KEY_SEPARATOR}"


class CachePort(Protocol):
    """The slice of a cache backend that authorization needs.

    Declared structurally so that this module compiles, runs and is testable
    without a cache implementation being present.
    """

    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None: ...

    #: Read-through. Authorization does not use it, but it is part of the shared
    #: backend's surface, and naming it here is what lets a module that only ever
    #: reads through — reporting, quote lookups — accept this same port without a
    #: cast.
    async def remember[T](
        self,
        key: str,
        ttl_seconds: int,
        loader: Callable[[], Awaitable[T]],
    ) -> T: ...

    async def delete(self, keys: str | Sequence[str]) -> None: ...

    async def invalidate_prefix(self, prefix: str) -> None: ...


class NoopCache:
    """Cache that stores nothing.

    The default whenever no backend is wired in, so that a missing cache is a
    performance property rather than a branch every caller has to handle.
    """

    async def get(self, key: str) -> Any | None:  # noqa: ARG002
        return None

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Intentionally empty: nothing is stored."""

    async def remember[T](
        self,
        key: str,  # noqa: ARG002
        ttl_seconds: int,  # noqa: ARG002
        loader: Callable[[], Awaitable[T]],
    ) -> T:
        return await loader()

    async def delete(self, keys: str | Sequence[str]) -> None:
        """Intentionally empty: nothing is stored."""

    async def invalidate_prefix(self, prefix: str) -> None:
        """Intentionally empty: nothing is stored."""


class UserPermissionsInvalidator(Protocol):
    """Implemented by the RBAC service, consumed by anything that edits roles."""

    async def invalidate_user_permissions(self, user_id: Any) -> None: ...


class NoopUserPermissionsInvalidator:
    """Default for services constructed without RBAC wiring, such as in tests."""

    async def invalidate_user_permissions(self, user_id: Any) -> None:
        """Intentionally empty: nothing is cached."""


@dataclass(frozen=True, slots=True)
class CachedUserPermissions:
    """Everything authorization needs about one user, cached as a single entry.

    The whole set is resolved at once so that one cache read answers every
    permission check for that user during a request.
    """

    is_active: bool
    scopes: dict[str, PermissionScope] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """Plain JSON-safe form, since a cache backend stores documents."""
        return {
            "isActive": self.is_active,
            "scopes": {key: scope.value for key, scope in self.scopes.items()},
        }

    @classmethod
    def from_payload(cls, payload: Any) -> CachedUserPermissions | None:
        """Rebuilds a snapshot, or returns ``None`` for anything unrecognised.

        A cache may hold an entry written by an older version of this code, and
        treating that as "not cached" is always safe, whereas trusting it is not.
        """
        if not isinstance(payload, dict):
            return None
        is_active = payload.get("isActive")
        raw_scopes = payload.get("scopes")
        if not isinstance(is_active, bool) or not isinstance(raw_scopes, dict):
            return None

        scopes: dict[str, PermissionScope] = {}
        for key, value in raw_scopes.items():
            if not isinstance(key, str) or value not in tuple(PermissionScope):
                return None
            scopes[key] = PermissionScope(value)
        return cls(is_active=is_active, scopes=scopes)
