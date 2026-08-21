"""Settings rules.

Reads go through the cache, writes go through the registry. Both halves matter:
a setting is read far more often than it is written, and a setting that could
hold anything would be useless to the modules that depend on it.

Deleting a setting is a reset, not a removal. The key keeps existing — it is
declared, not created — so once the row is gone the registry default is served
again and a reader never sees a gap.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.serializers import format_datetime
from app.db.models.setting import OrganizationSetting
from app.modules.audit import AuditEvent, AuditService
from app.modules.settings.cache_keys import setting_value_key, settings_list_key
from app.modules.settings.registry import (
    SETTING_KEYS,
    ensure_setting_key,
    parse_setting_value,
    read_stored_value,
    setting_definition,
)
from app.modules.settings.schemas import SettingOut, UpsertSettingRequest
from app.modules.settings.types import (
    DEFAULT_SETTINGS_TTL_SECONDS,
    SETTING_AUDIT_ENTITY_TYPE,
    SETTING_DELETED,
    SETTING_NOT_FOUND,
    SETTING_UPDATED,
    NoopSettingsCache,
    SettingsAccess,
    SettingsCache,
)


def to_setting_out(key: str, row: OrganizationSetting | None) -> SettingOut:
    """Renders a key, whether or not a row has ever been written for it."""
    definition = setting_definition(key)
    if row is None:
        return SettingOut(
            key=key,
            value=definition.default_value,
            description=definition.description,
            updated_by_id=None,
            updated_at=None,
            source="default",
        )
    return SettingOut(
        key=key,
        value=read_stored_value(key, row.value),
        description=row.description or definition.description,
        updated_by_id=row.updated_by_id,
        updated_at=format_datetime(row.updated_at),
        source="database",
    )


def decode_setting(payload: Any) -> SettingOut | None:
    """Rebuilds a DTO from a cached document, or reports it unusable.

    An entry written by an older version of this code is treated as a miss:
    reading it as current would publish a shape the client no longer knows.
    """
    try:
        return SettingOut.model_validate(payload)
    except ValidationError:
        return None


def decode_settings(payload: Any) -> list[SettingOut] | None:
    """Same for a cached listing; one unusable entry discards the whole page."""
    if not isinstance(payload, list):
        return None
    items = [decode_setting(entry) for entry in payload]
    if any(item is None for item in items):
        return None
    return [item for item in items if item is not None]


class SettingsService:
    """Reads and writes organization settings on one session."""

    def __init__(
        self,
        session: AsyncSession,
        cache: SettingsCache | None = None,
        ttl_seconds: int = DEFAULT_SETTINGS_TTL_SECONDS,
    ) -> None:
        self._session = session
        self._audit = AuditService(session)
        self._cache: SettingsCache = cache if cache is not None else NoopSettingsCache()
        self._ttl_seconds = ttl_seconds

    async def list(self) -> list[SettingOut]:
        """Every declared key, whether or not it has a row."""
        cache_key = settings_list_key()
        cached = decode_settings(await self._cached(cache_key))
        if cached is not None:
            return cached

        rows = await self._session.execute(
            select(OrganizationSetting).where(OrganizationSetting.key.in_(SETTING_KEYS))
        )
        by_key = {row.key: row for row in rows.scalars().all()}
        # A declared key without a row is still listed, showing its default.
        items = [to_setting_out(key, by_key.get(key)) for key in SETTING_KEYS]
        await self._store(
            cache_key, [item.model_dump(mode="json", by_alias=True) for item in items]
        )
        return items

    async def get_by_key(self, raw_key: str) -> SettingOut:
        key = ensure_setting_key(raw_key)
        cache_key = setting_value_key(key)

        cached = decode_setting(await self._cached(cache_key))
        if cached is not None:
            return cached

        item = to_setting_out(key, await self._find_row(key))
        await self._store(cache_key, item.model_dump(mode="json", by_alias=True))
        return item

    async def get(self, key: str) -> Any:
        """Typed accessor for other modules; falls back to the declared default."""
        return (await self.get_by_key(key)).value

    async def upsert(
        self, access: SettingsAccess, raw_key: str, data: UpsertSettingRequest
    ) -> SettingOut:
        key = ensure_setting_key(raw_key)
        definition = setting_definition(key)
        value = parse_setting_value(key, data.value)
        # A description of `null` means "use the declared one" rather than
        # "store an empty description".
        description = data.description or definition.description

        row = await self._find_row(key)
        before = to_setting_out(key, row) if row is not None else None
        if row is None:
            row = OrganizationSetting(id=uuid.uuid4(), key=key)
            self._session.add(row)
        row.value = value
        row.description = description
        row.updated_by_id = access.actor_id
        await self._session.flush()

        after = to_setting_out(key, row)
        await self._audit.record(
            AuditEvent(
                actor_id=access.actor_id,
                action=SETTING_UPDATED,
                entity_type=SETTING_AUDIT_ENTITY_TYPE,
                entity_id=row.id,
                changes={
                    "before": before.model_dump(mode="json", by_alias=True) if before else None,
                    "after": after.model_dump(mode="json", by_alias=True),
                },
                ip_address=access.ip_address,
            )
        )
        await self._invalidate(key)
        return after

    async def remove(self, access: SettingsAccess, raw_key: str) -> None:
        """Drops the row, which restores the declared default."""
        key = ensure_setting_key(raw_key)
        row = await self._find_row(key)
        if row is None:
            raise NotFoundError("Setting not found", SETTING_NOT_FOUND)

        before = to_setting_out(key, row)
        row_id = row.id
        await self._session.delete(row)
        await self._session.flush()

        after = to_setting_out(key, None)
        await self._audit.record(
            AuditEvent(
                actor_id=access.actor_id,
                action=SETTING_DELETED,
                entity_type=SETTING_AUDIT_ENTITY_TYPE,
                entity_id=row_id,
                # Removing a row restores the registry default rather than
                # erasing the setting, which is what `after` reflects.
                changes={
                    "before": before.model_dump(mode="json", by_alias=True),
                    "after": after.model_dump(mode="json", by_alias=True),
                },
                ip_address=access.ip_address,
            )
        )
        await self._invalidate(key)

    async def _find_row(self, key: str) -> OrganizationSetting | None:
        result = await self._session.execute(
            select(OrganizationSetting).where(OrganizationSetting.key == key)
        )
        return result.scalar_one_or_none()

    async def _cached(self, cache_key: str) -> Any | None:
        """Reads an entry, treating any cache failure as a miss.

        The bundled cache service already fails open, but the dependency is
        injectable: a cache outage must degrade latency, never turn a read into
        an error.
        """
        with contextlib.suppress(Exception):
            return await self._cache.get(cache_key)
        return None

    async def _store(self, cache_key: str, payload: Any) -> None:
        with contextlib.suppress(Exception):
            await self._cache.set(cache_key, payload, self._ttl_seconds)

    async def _invalidate(self, key: str) -> None:
        """Drops the entry for the key and the listing that contains it."""
        with contextlib.suppress(Exception):
            await self._cache.delete([setting_value_key(key), settings_list_key()])
