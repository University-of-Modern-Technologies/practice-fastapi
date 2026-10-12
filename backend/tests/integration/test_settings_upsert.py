"""Scenario — a setting that already has a row can be written again.

This is the property a stubbed session cannot check. ``updated_at`` is
refreshed by the database rather than by Python, so after a plain flush the ORM
holds it expired, and reading it on an async session raises instead of loading
— which turned every edit of an existing setting into a 500 and rolled the
change back. Only a real PostgreSQL round trip shows whether the write hands
back a row that can be rendered as it stands.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serializers import format_datetime
from app.db.models.audit import AuditLog
from app.db.models.setting import OrganizationSetting
from app.modules.settings.schemas import UpsertSettingRequest
from app.modules.settings.service import SettingsService
from app.modules.settings.types import SETTING_UPDATED, SettingsAccess
from tests.integration.conftest import create_user

KEY = "organization.name"


async def _stored(session: AsyncSession) -> OrganizationSetting:
    """The row as the database holds it, not as the identity map remembers it."""
    statement = (
        select(OrganizationSetting)
        .where(OrganizationSetting.key == KEY)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalar_one()


async def _row_count(session: AsyncSession) -> int:
    total = await session.scalar(
        select(func.count()).select_from(OrganizationSetting).where(OrganizationSetting.key == KEY)
    )
    return int(total or 0)


async def test_a_setting_with_a_row_can_be_written_again(db_session: AsyncSession) -> None:
    first_author = await create_user(db_session)
    second_author = await create_user(db_session)
    service = SettingsService(db_session)

    created = await service.upsert(
        SettingsAccess(actor_id=first_author.id), KEY, UpsertSettingRequest(value="Acme")
    )
    await db_session.commit()
    assert created.source == "database"
    assert created.updated_at is not None

    # The row read before the write now sits in the session, exactly as it does
    # on a request that edits a setting someone has already written.
    updated = await service.upsert(
        SettingsAccess(actor_id=second_author.id, ip_address="203.0.113.7"),
        KEY,
        UpsertSettingRequest(value="Globex", description="Trading name"),
    )
    await db_session.commit()

    stored = await _stored(db_session)
    assert updated.key == KEY
    assert updated.value == "Globex"
    assert updated.description == "Trading name"
    assert updated.updated_by_id == second_author.id
    assert updated.updated_at == format_datetime(stored.updated_at)
    assert updated.source == "database"
    assert stored.value == "Globex"
    assert stored.updated_by_id == second_author.id
    assert await _row_count(db_session) == 1


async def test_a_row_written_by_an_earlier_request_can_be_edited(
    db_session: AsyncSession,
) -> None:
    author = await create_user(db_session)
    editor = await create_user(db_session)
    await SettingsService(db_session).upsert(
        SettingsAccess(actor_id=author.id), KEY, UpsertSettingRequest(value="Acme")
    )
    await db_session.commit()
    row_id = (await _stored(db_session)).id
    # A later request starts with nothing in its identity map.
    db_session.expunge_all()

    updated = await SettingsService(db_session).upsert(
        SettingsAccess(actor_id=editor.id), KEY, UpsertSettingRequest(value="Initech")
    )
    await db_session.commit()

    stored = await _stored(db_session)
    assert stored.id == row_id
    assert updated.value == "Initech"
    assert updated.updated_by_id == editor.id
    assert updated.updated_at == format_datetime(stored.updated_at)

    entries = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_id == row_id, AuditLog.action == SETTING_UPDATED
                )
            )
        )
        .scalars()
        .all()
    )
    # Both entries share one transaction timestamp here, so the edit is told
    # apart from the first write by having something before it.
    edits = [entry for entry in entries if entry.changes and entry.changes["before"] is not None]
    assert len(entries) == 2
    assert len(edits) == 1
    changes = edits[0].changes
    assert changes is not None
    assert changes["before"]["value"] == "Acme"
    assert changes["after"] == updated.model_dump(mode="json", by_alias=True)


async def test_two_writes_of_one_key_leave_one_row(db_session: AsyncSession) -> None:
    author = await create_user(db_session)
    access = SettingsAccess(actor_id=author.id)
    service = SettingsService(db_session)

    for value in ("Acme", "Globex", "Initech"):
        await service.upsert(access, KEY, UpsertSettingRequest(value=value))

    assert await _row_count(db_session) == 1
    assert (await _stored(db_session)).value == "Initech"
