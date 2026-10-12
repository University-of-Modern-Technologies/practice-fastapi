"""Wire contract of the role and permission endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from app.core.responses import CamelModel
from app.core.serializers import UtcDatetime
from app.db.enums import PermissionScope
from app.modules.rbac.types import create_permission_key

MAX_PERMISSION_PART_LENGTH = 64
MAX_PERMISSION_KEY_LENGTH = 100
MAX_PERMISSIONS_PER_ROLE = 100
MAX_ROLE_NAME_LENGTH = 64
MAX_ROLE_DESCRIPTION_LENGTH = 255

#: A resource or an action: lowercase, starting with a letter. The two halves
#: are validated separately so that a colon can never enter either of them and
#: turn one key into two. Surrounding whitespace is dropped first.
PermissionPart = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_PERMISSION_PART_LENGTH,
        pattern=r"^[a-z][a-z0-9_-]*$",
    ),
]

#: Free text, trimmed before its length is checked: a role named with stray
#: spaces is the same role, and one named with spaces only has no name.
RoleName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_ROLE_NAME_LENGTH)
]
RoleDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_ROLE_DESCRIPTION_LENGTH),
]


class PermissionAssignment(CamelModel):
    """One permission granted to a role at a given breadth."""

    model_config = ConfigDict(extra="forbid")

    resource: PermissionPart
    action: PermissionPart
    scope: PermissionScope

    @model_validator(mode="after")
    def _check_key_length(self) -> PermissionAssignment:
        if len(create_permission_key(self.resource, self.action)) > MAX_PERMISSION_KEY_LENGTH:
            message = f"Permission key must not exceed {MAX_PERMISSION_KEY_LENGTH} characters"
            raise ValueError(message)
        return self


PermissionAssignments = Annotated[
    list[PermissionAssignment], Field(max_length=MAX_PERMISSIONS_PER_ROLE)
]


def _reject_duplicates(permissions: list[PermissionAssignment]) -> list[PermissionAssignment]:
    """Rejects a payload that grants the same key twice.

    Silently keeping the last one would make the stored breadth depend on array
    order, which is not something the caller can see in their own request.
    """
    seen: set[str] = set()
    for permission in permissions:
        key = create_permission_key(permission.resource, permission.action)
        if key in seen:
            message = f"Duplicate permission key: {key}"
            raise ValueError(message)
        seen.add(key)
    return permissions


class CreateRoleRequest(CamelModel):
    """Body of ``POST /rbac/roles``."""

    model_config = ConfigDict(extra="forbid")

    name: RoleName
    description: RoleDescription | None = None
    permissions: PermissionAssignments

    @model_validator(mode="after")
    def _unique_permissions(self) -> CreateRoleRequest:
        _reject_duplicates(self.permissions)
        return self


class ReplaceRolePermissionsRequest(CamelModel):
    """Body of ``PUT /rbac/roles/{id}/permissions``."""

    model_config = ConfigDict(extra="forbid")

    permissions: PermissionAssignments

    @model_validator(mode="after")
    def _unique_permissions(self) -> ReplaceRolePermissionsRequest:
        _reject_duplicates(self.permissions)
        return self


class RoleOut(CamelModel):
    """A role with its complete grant list."""

    id: uuid.UUID
    name: str
    description: str | None
    permissions: list[PermissionAssignment]
    created_at: UtcDatetime
    updated_at: UtcDatetime


class PermissionCheckOut(CamelModel):
    """Answer of ``GET /rbac/check/{resource}/{action}``.

    ``scope`` is reported alongside ``allowed`` because the client needs to know
    not only whether an action is possible but on which records.
    """

    allowed: bool
    scope: PermissionScope | None
