"""Vocabulary of organization settings."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

__all__ = [
    "DEFAULT_SETTINGS_TTL_SECONDS",
    "INVALID_SETTING_VALUE",
    "SETTING_AUDIT_ENTITY_TYPE",
    "SETTING_DELETED",
    "SETTING_NOT_FOUND",
    "SETTING_UPDATED",
    "UNKNOWN_SETTING_KEY",
    "NoopSettingsCache",
    "SettingSource",
    "SettingsAccess",
    "SettingsCache",
]

#: Machine codes shared between the registry, the service and their tests.
UNKNOWN_SETTING_KEY = "UNKNOWN_SETTING_KEY"
INVALID_SETTING_VALUE = "INVALID_SETTING_VALUE"
SETTING_NOT_FOUND = "SETTING_NOT_FOUND"

#: The table the audit trail points at.
SETTING_AUDIT_ENTITY_TYPE = "organization_setting"

SETTING_UPDATED = "setting.updated"
SETTING_DELETED = "setting.deleted"

#: Settings change rarely and are read on almost every request that prices
#: something, which is what makes them worth caching for minutes rather than
#: seconds.
#: Key the composition root reads to learn which warehouse an order draws on.
#: Named here so the orders wiring does not repeat a string literal.
DEFAULT_WAREHOUSE_SETTING = "warehouse.defaultCode"

DEFAULT_SETTINGS_TTL_SECONDS = 300

#: Where the value in a DTO came from. ``default`` means no row exists yet and
#: the registry default is being served.
SettingSource = Literal["database", "default"]


@dataclass(frozen=True, slots=True)
class SettingsAccess:
    """Who is changing a setting, and from where."""

    actor_id: uuid.UUID
    ip_address: str | None = None


class SettingsCache(Protocol):
    """The slice of a cache backend this module needs.

    Declared structurally so the module compiles, runs and is testable without
    any cache implementation being present.
    """

    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, keys: str | Sequence[str]) -> None: ...


class NoopSettingsCache:
    """Cache that stores nothing.

    The default whenever no backend is wired in, so that a missing cache is a
    performance property rather than a branch every call site has to handle.
    """

    async def get(self, key: str) -> Any | None:  # noqa: ARG002
        return None

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Intentionally empty: nothing is stored."""

    async def delete(self, keys: str | Sequence[str]) -> None:
        """Intentionally empty: nothing is stored."""
