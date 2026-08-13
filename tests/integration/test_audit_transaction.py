"""Scenario 2 — the audit trail commits and rolls back with what it describes.

This is the one property of the trail that cannot be checked with a stubbed
session: it depends on the entry and the business change sharing a real
PostgreSQL transaction. An audit trail that can disagree with the data it
describes is worse than no trail at all, because it is trusted.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.db.enums import PermissionScope
from app.db.models.audit import AuditLog
from app.db.models.contact import Contact
from app.modules.contacts.schemas import CreateContactRequest
from app.modules.contacts.service import ContactsService
from app.modules.contacts.types import ContactAccess
from tests.integration.conftest import create_user


async def _count(session: AsyncSession, entity: type[Contact] | type[AuditLog]) -> int:
    total = await session.scalar(select(func.count()).select_from(entity))
    return int(total or 0)


def _payload() -> CreateContactRequest:
    token = uuid.uuid4().hex[:12]
    return CreateContactRequest(
        first_name="Ada",
        last_name=f"Byron-{token}",
        email=f"ada-{token}@example.com",
    )


async def test_the_entry_and_the_change_are_written_together(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    service = ContactsService(db_session)
    access = ContactAccess(actor_id=owner.id, scope=PermissionScope.ALL, ip_address="203.0.113.7")

    contact = await service.create(access, _payload())
    await db_session.commit()

    entries = (
        (await db_session.execute(select(AuditLog).where(AuditLog.entity_id == contact.id)))
        .scalars()
        .all()
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry.action == "contact.created"
    assert entry.actor_id == owner.id
    # The address the router stamped travels all the way into the column.
    assert str(entry.ip_address) == "203.0.113.7"


async def test_a_rolled_back_change_leaves_no_entry_behind(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    await db_session.commit()
    contacts_before = await _count(db_session, Contact)
    entries_before = await _count(db_session, AuditLog)

    service = ContactsService(db_session)
    access = ContactAccess(actor_id=owner.id, scope=PermissionScope.ALL)

    savepoint = await db_session.begin_nested()
    await service.create(access, _payload())
    # Both rows exist inside the transaction...
    assert await _count(db_session, Contact) == contacts_before + 1
    assert await _count(db_session, AuditLog) == entries_before + 1

    await savepoint.rollback()

    # ...and neither survives it. The trail cannot describe a change that never
    # happened, because it is written on the very same transaction.
    assert await _count(db_session, Contact) == contacts_before
    assert await _count(db_session, AuditLog) == entries_before


async def test_a_failing_operation_records_nothing(db_session: AsyncSession) -> None:
    """A duplicate is rejected after the trail would already have been written."""
    owner = await create_user(db_session)
    service = ContactsService(db_session)
    access = ContactAccess(actor_id=owner.id, scope=PermissionScope.ALL)
    payload = _payload()
    await service.create(access, payload)
    await db_session.commit()

    entries_before = await _count(db_session, AuditLog)

    savepoint = await db_session.begin_nested()
    with pytest.raises(ConflictError):
        await service.create(access, payload)
    await savepoint.rollback()

    assert await _count(db_session, AuditLog) == entries_before
