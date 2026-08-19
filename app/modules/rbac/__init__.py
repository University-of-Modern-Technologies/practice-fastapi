"""Authorization: what the caller may do, and to which records.

Two imports here are deliberately *not* re-exported, and the reason is worth
stating. Authentication needs the permission-key helpers below, while this
module's dependencies need authentication's identity — so eagerly importing
``dependencies`` or ``router`` from this package would close an import cycle
between the two. They are reached through their own modules instead:

    from app.modules.rbac.dependencies import require_permission
    from app.modules.rbac.router import create_rbac_router
"""

from __future__ import annotations

from app.modules.rbac.schemas import (
    CreateRoleRequest,
    PermissionAssignment,
    PermissionCheckOut,
    ReplaceRolePermissionsRequest,
    RoleOut,
)
from app.modules.rbac.service import RbacService
from app.modules.rbac.types import (
    CachedUserPermissions,
    CachePort,
    NoopCache,
    PermissionScope,
    UserPermissionsInvalidator,
    create_permission_key,
    parse_permission_key,
    user_permissions_key,
    user_permissions_prefix,
)

__all__ = [
    "CachePort",
    "CachedUserPermissions",
    "CreateRoleRequest",
    "NoopCache",
    "PermissionAssignment",
    "PermissionCheckOut",
    "PermissionScope",
    "RbacService",
    "ReplaceRolePermissionsRequest",
    "RoleOut",
    "UserPermissionsInvalidator",
    "create_permission_key",
    "parse_permission_key",
    "user_permissions_key",
    "user_permissions_prefix",
]
