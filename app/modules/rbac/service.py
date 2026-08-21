"""Authorization rules.

Two responsibilities live here. The first answers "may this user do this?" and
is on the hot path of nearly every request, so the answer is cached as one
snapshot per user. The second edits roles, and every edit that could change an
answer drops the affected snapshots immediately — a stale permission is a
security bug, not a stale read.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.enums import PermissionScope
from app.db.models.rbac import Permission, Role, RolePermission, UserRole
from app.db.models.user import User
from app.modules.rbac.schemas import (
    CreateRoleRequest,
    PermissionAssignment,
    ReplaceRolePermissionsRequest,
    RoleOut,
)
from app.modules.rbac.types import (
    DEFAULT_PERMISSIONS_TTL_SECONDS,
    CachedUserPermissions,
    CachePort,
    NoopCache,
    create_permission_key,
    parse_permission_key,
    user_permissions_key,
    user_permissions_prefix,
)

_ROLE_GRANTS = selectinload(Role.permissions).selectinload(RolePermission.permission)


def to_role_out(role: Role) -> RoleOut:
    """Renders a role, dropping any grant whose stored key is unreadable."""
    permissions: list[PermissionAssignment] = []
    for grant in role.permissions:
        parts = parse_permission_key(grant.permission.key)
        if parts is None:
            continue
        permissions.append(
            PermissionAssignment(resource=parts.resource, action=parts.action, scope=grant.scope)
        )
    permissions.sort(key=lambda item: create_permission_key(item.resource, item.action))

    return RoleOut(
        id=role.id,
        name=role.name,
        description=role.description,
        permissions=permissions,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


class RbacService:
    """Permission lookups and role administration."""

    def __init__(
        self,
        session: AsyncSession,
        cache: CachePort | None = None,
        ttl_seconds: int = DEFAULT_PERMISSIONS_TTL_SECONDS,
    ) -> None:
        self._session = session
        self._cache: CachePort = cache if cache is not None else NoopCache()
        self._ttl_seconds = ttl_seconds

    async def get_permission_scope(
        self, user_id: uuid.UUID, resource: str, action: str
    ) -> PermissionScope | None:
        """The breadth this user holds for one capability, or ``None``.

        A disabled account resolves to ``None`` for everything, so deactivating
        a user is enough to stop them acting even while their access token is
        still within its lifetime.
        """
        permissions = await self._load_cached_permissions(user_id)
        if not permissions.is_active:
            return None
        return permissions.scopes.get(create_permission_key(resource, action))

    async def invalidate_user_permissions(self, user_id: uuid.UUID) -> None:
        """Drops one user's snapshot after their roles or status changed."""
        await self._cache.delete(user_permissions_key(str(user_id)))

    async def invalidate_all_user_permissions(self) -> None:
        """Drops every snapshot.

        A role edit affects every holder of that role, and the cache does not
        keep the reverse mapping, so the namespace goes as a whole.
        """
        await self._cache.invalidate_prefix(user_permissions_prefix())

    async def list_roles(self) -> list[RoleOut]:
        result = await self._session.execute(
            select(Role).options(_ROLE_GRANTS).order_by(Role.name.asc())
        )
        return [to_role_out(role) for role in result.scalars().unique().all()]

    async def create_role(self, data: CreateRoleRequest) -> RoleOut:
        if await self._find_role_id_by_name(data.name) is not None:
            raise ConflictError("A role with this name already exists", "ROLE_ALREADY_EXISTS")

        ids_by_key = await self._resolve_permission_ids(data.permissions)
        role = Role(id=uuid.uuid4(), name=data.name, description=data.description)
        self._session.add(role)
        await self._session.flush()

        self._add_grants(role.id, data.permissions, ids_by_key)
        await self._session.flush()
        return await self._read_role(role.id)

    async def replace_role_permissions(
        self, role_id: uuid.UUID, data: ReplaceRolePermissionsRequest
    ) -> RoleOut:
        role = await self._session.get(Role, role_id)
        if role is None:
            raise NotFoundError("Role not found", "ROLE_NOT_FOUND")

        ids_by_key = await self._resolve_permission_ids(data.permissions)
        await self._session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
        self._add_grants(role_id, data.permissions, ids_by_key)
        await self._session.flush()

        replaced = await self._read_role(role_id)
        # Every holder of this role now carries a snapshot that no longer
        # matches the database.
        await self.invalidate_all_user_permissions()
        return replaced

    async def _load_cached_permissions(self, user_id: uuid.UUID) -> CachedUserPermissions:
        key = user_permissions_key(str(user_id))
        cached = CachedUserPermissions.from_payload(await self._cache.get(key))
        if cached is not None:
            return cached

        permissions = await self._load_permissions(user_id)
        await self._cache.set(key, permissions.to_payload(), self._ttl_seconds)
        return permissions

    async def _load_permissions(self, user_id: uuid.UUID) -> CachedUserPermissions:
        """Reads the user's entire grant set in a single round trip."""
        result = await self._session.execute(
            select(User)
            .options(
                selectinload(User.user_roles)
                .selectinload(UserRole.role)
                .selectinload(Role.permissions)
                .selectinload(RolePermission.permission)
            )
            .where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return CachedUserPermissions(is_active=False)

        scopes: dict[str, PermissionScope] = {}
        for user_role in user.user_roles:
            for grant in user_role.role.permissions:
                # Roles are additive: the widest grant wins when two of them
                # name the same permission.
                if scopes.get(grant.permission.key) != PermissionScope.ALL:
                    scopes[grant.permission.key] = grant.scope
        return CachedUserPermissions(is_active=user.is_active, scopes=scopes)

    async def _find_role_id_by_name(self, name: str) -> uuid.UUID | None:
        result = await self._session.execute(select(Role.id).where(Role.name == name))
        return result.scalar_one_or_none()

    async def _resolve_permission_ids(
        self, permissions: list[PermissionAssignment]
    ) -> dict[str, uuid.UUID]:
        """Maps requested keys onto stored permission rows.

        Permissions are a fixed catalogue rather than free text, so an unknown
        key is a client mistake and is reported as one instead of being created.
        """
        keys = [create_permission_key(item.resource, item.action) for item in permissions]
        if not keys:
            return {}

        result = await self._session.execute(
            select(Permission.key, Permission.id).where(Permission.key.in_(keys))
        )
        ids_by_key: dict[str, uuid.UUID] = dict(result.tuples().all())

        unknown = [key for key in keys if key not in ids_by_key]
        if unknown:
            raise AppError("Unknown permission", 400, "UNKNOWN_PERMISSION", {"keys": unknown})
        return ids_by_key

    def _add_grants(
        self,
        role_id: uuid.UUID,
        permissions: list[PermissionAssignment],
        ids_by_key: dict[str, uuid.UUID],
    ) -> None:
        for item in permissions:
            self._session.add(
                RolePermission(
                    role_id=role_id,
                    permission_id=ids_by_key[create_permission_key(item.resource, item.action)],
                    scope=item.scope,
                )
            )

    async def _read_role(self, role_id: uuid.UUID) -> RoleOut:
        result = await self._session.execute(
            select(Role).options(_ROLE_GRANTS).where(Role.id == role_id)
        )
        role = result.scalars().unique().one_or_none()
        if role is None:
            raise NotFoundError("Role not found", "ROLE_NOT_FOUND")
        return to_role_out(role)
