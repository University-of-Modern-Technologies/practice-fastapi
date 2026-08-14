"""Scenario 4 — an `OWN` grant narrows the rows PostgreSQL returns.

The stubbed version of this check can only prove that a predicate was appended
to a statement. This one proves the predicate does what it is there for, which
is the difference between a test and a spelling check: a silent authorization
hole looks exactly like a passing unit test until somebody reads real rows.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.db.enums import PermissionScope
from app.modules.contacts.schemas import ContactListParams, CreateContactRequest
from app.modules.contacts.service import ContactsService
from app.modules.contacts.types import ContactAccess
from app.modules.rbac.service import RbacService
from app.modules.rbac.types import NoopCache
from tests.integration.conftest import create_contact, create_user, grant

CACHE_TTL_SECONDS = 60


async def test_the_stored_grant_is_what_the_service_reports(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await grant(db_session, user, "contacts:read", PermissionScope.OWN)
    rbac = RbacService(db_session, NoopCache(), CACHE_TTL_SECONDS)

    assert await rbac.get_permission_scope(user.id, "contacts", "read") is PermissionScope.OWN
    # A permission the role never received is not a narrower grant, it is none.
    assert await rbac.get_permission_scope(user.id, "contacts", "delete") is None


async def test_the_widest_grant_wins_when_two_roles_overlap(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await grant(db_session, user, "contacts:read", PermissionScope.OWN)
    await grant(db_session, user, "contacts:read", PermissionScope.ALL)
    rbac = RbacService(db_session, NoopCache(), CACHE_TTL_SECONDS)

    # A narrow role cannot take away what a wider one already allows.
    assert await rbac.get_permission_scope(user.id, "contacts", "read") is PermissionScope.ALL


async def test_own_returns_only_the_caller_s_rows(db_session: AsyncSession) -> None:
    owner = await create_user(db_session, name="Owner")
    stranger = await create_user(db_session, name="Stranger")
    mine = [await create_contact(db_session, owner) for _ in range(2)]
    for _ in range(3):
        await create_contact(db_session, stranger)
    await db_session.flush()

    service = ContactsService(db_session)
    narrow, narrow_total = await service.list(
        ContactAccess(actor_id=owner.id, scope=PermissionScope.OWN), ContactListParams()
    )

    assert narrow_total == len(mine)
    assert {row.id for row in narrow} == {contact.id for contact in mine}


async def test_all_returns_everybody_s_rows(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    stranger = await create_user(db_session)
    await create_contact(db_session, owner)
    await create_contact(db_session, stranger)
    await db_session.flush()

    service = ContactsService(db_session)
    _, total = await service.list(
        ContactAccess(actor_id=owner.id, scope=PermissionScope.ALL), ContactListParams()
    )

    assert total >= 2


async def test_a_narrow_caller_cannot_read_a_row_by_its_id(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    stranger = await create_user(db_session)
    theirs = await create_contact(db_session, stranger)
    await db_session.flush()

    service = ContactsService(db_session)

    with pytest.raises(NotFoundError):
        await service.get_by_id(
            ContactAccess(actor_id=owner.id, scope=PermissionScope.OWN), theirs.id
        )


async def test_a_narrow_caller_cannot_hand_a_record_to_somebody_else(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    stranger = await create_user(db_session)
    await db_session.flush()

    service = ContactsService(db_session)

    with pytest.raises(ForbiddenError):
        await service.create(
            ContactAccess(actor_id=owner.id, scope=PermissionScope.OWN),
            CreateContactRequest(
                owner_id=stranger.id,
                first_name="Ada",
                last_name="Byron",
                email="handover@example.com",
            ),
        )
