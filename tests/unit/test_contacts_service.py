"""Contact rules: who sees what, what counts as a duplicate, what a delete does."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.db.enums import PermissionScope
from app.db.models.contact import Contact
from app.modules.audit import AuditEvent, AuditService
from app.modules.contacts.schemas import (
    ContactListParams,
    CreateContactRequest,
    UpdateContactRequest,
)
from app.modules.contacts.service import ContactsService
from app.modules.contacts.types import ContactAccess, ContactSortField

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)


class FakeScalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return list(self._values)

    def one_or_none(self) -> Any:
        return self._values[0] if self._values else None


class FakeResult:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._values)


class FakeSession:
    """A scripted stand-in: each call pops the next prepared answer."""

    def __init__(self) -> None:
        self.execute_queue: list[list[Any]] = []
        self.scalar_queue: list[Any] = []
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.flushes = 0

    async def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.execute_queue.pop(0) if self.execute_queue else [])

    async def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        return self.scalar_queue.pop(0) if self.scalar_queue else None

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, instance: Any) -> None:
        # Stands in for the server-side defaults, which only reach the instance
        # once the row has been read back.
        if getattr(instance, "created_at", None) is None:
            instance.created_at = NOW
        instance.updated_at = NOW


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def make_service(
    session: FakeSession,
    audit: RecordingAudit | None = None,
) -> ContactsService:
    return ContactsService(
        cast("AsyncSession", session),
        audit=cast("AuditService", audit if audit is not None else RecordingAudit()),
    )


def make_contact(owner_id: uuid.UUID | None = None) -> Contact:
    return Contact(
        id=uuid.uuid4(),
        owner_id=owner_id if owner_id is not None else uuid.uuid4(),
        first_name="Ada",
        last_name="Byron",
        email="ada@example.com",
        phone="+380671234567",
        company="Analytical Engines",
        notes=None,
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )


def own(actor_id: uuid.UUID) -> ContactAccess:
    return ContactAccess(actor_id=actor_id, scope=PermissionScope.OWN, ip_address="203.0.113.7")


def everything(actor_id: uuid.UUID) -> ContactAccess:
    return ContactAccess(actor_id=actor_id, scope=PermissionScope.ALL, ip_address="203.0.113.7")


def sql(statement: Any) -> str:
    return str(statement)


def bound_values(statement: Any) -> list[Any]:
    return list(statement.compile().params.values())


async def test_a_narrow_grant_is_applied_to_the_query_not_to_the_result() -> None:
    actor_id = uuid.uuid4()
    session = FakeSession()
    session.scalar_queue = [1]
    session.execute_queue = [[make_contact(actor_id)]]
    service = make_service(session)

    await service.list(
        own(actor_id),
        # A manager asking for somebody else's contacts is not refused, they
        # are simply answered about their own.
        ContactListParams.model_validate({"ownerId": str(uuid.uuid4())}),
    )

    counted, selected = session.statements
    assert "contacts.owner_id" in sql(counted)
    assert actor_id in bound_values(counted)
    assert actor_id in bound_values(selected)


async def test_a_wide_grant_may_ask_about_one_owner() -> None:
    owner_id = uuid.uuid4()
    session = FakeSession()
    session.scalar_queue = [0]
    session.execute_queue = [[]]
    service = make_service(session)

    await service.list(
        everything(uuid.uuid4()), ContactListParams.model_validate({"ownerId": str(owner_id)})
    )

    assert owner_id in bound_values(session.statements[0])


async def test_deleted_contacts_never_reach_a_reader() -> None:
    session = FakeSession()
    session.scalar_queue = [0]
    session.execute_queue = [[]]
    service = make_service(session)

    await service.list(everything(uuid.uuid4()), ContactListParams())

    assert "contacts.deleted_at IS NULL" in sql(session.statements[1])


async def test_a_search_covers_name_address_number_and_company() -> None:
    session = FakeSession()
    session.scalar_queue = [0]
    session.execute_queue = [[]]
    service = make_service(session)

    await service.list(
        everything(uuid.uuid4()), ContactListParams.model_validate({"search": "byron"})
    )

    statement = sql(session.statements[1])
    for column in ("first_name", "last_name", "email", "phone", "company"):
        assert f"lower(contacts.{column})" in statement


async def test_a_wildcard_in_a_search_term_is_escaped() -> None:
    session = FakeSession()
    session.scalar_queue = [0]
    session.execute_queue = [[]]
    service = make_service(session)

    await service.list(
        everything(uuid.uuid4()), ContactListParams.model_validate({"search": "100%"})
    )

    # Unescaped, `%` would turn a search into "match everything".
    assert "%100\\%%" in bound_values(session.statements[1])


async def test_sorting_uses_the_column_the_enum_names() -> None:
    session = FakeSession()
    session.scalar_queue = [0]
    session.execute_queue = [[]]
    service = make_service(session)

    await service.list(
        everything(uuid.uuid4()),
        ContactListParams.model_validate({"sortBy": ContactSortField.COMPANY, "sortOrder": "asc"}),
    )

    # Tie-broken by id so a page boundary cannot repeat or drop a row.
    assert "ORDER BY contacts.company ASC, contacts.id ASC" in sql(session.statements[1])


async def test_a_contact_of_another_owner_is_reported_as_missing() -> None:
    session = FakeSession()
    session.execute_queue = [[]]  # the scoped query found nothing
    service = make_service(session)

    with pytest.raises(NotFoundError) as error:
        await service.get_by_id(own(uuid.uuid4()), uuid.uuid4())

    # A 403 here would confirm the id exists and make the endpoint enumerable.
    assert error.value.code == "CONTACT_NOT_FOUND"
    assert error.value.status_code == 404


async def test_creating_a_contact_makes_its_creator_the_owner() -> None:
    actor_id = uuid.uuid4()
    session = FakeSession()
    session.scalar_queue = [None]  # no duplicate channel
    audit = RecordingAudit()
    service = make_service(session, audit)

    created = await service.create(
        own(actor_id),
        CreateContactRequest.model_validate(
            {"firstName": "Ada", "lastName": "Byron", "email": "ada@example.com"}
        ),
    )

    assert created.owner_id == actor_id
    assert [event.action for event in audit.events] == ["contact.created"]
    assert audit.events[0].ip_address == "203.0.113.7"


async def test_a_narrow_grant_cannot_hand_a_contact_to_somebody_else() -> None:
    session = FakeSession()
    service = make_service(session)

    with pytest.raises(ForbiddenError):
        await service.create(
            own(uuid.uuid4()),
            CreateContactRequest.model_validate(
                {
                    "ownerId": str(uuid.uuid4()),
                    "firstName": "Ada",
                    "lastName": "Byron",
                    "email": "ada@example.com",
                }
            ),
        )

    assert session.added == []


async def test_a_channel_already_in_use_is_a_conflict() -> None:
    session = FakeSession()
    session.scalar_queue = [uuid.uuid4()]  # a live contact already answers here
    service = make_service(session)

    with pytest.raises(ConflictError) as error:
        await service.create(
            everything(uuid.uuid4()),
            CreateContactRequest.model_validate(
                {"firstName": "Ada", "lastName": "Byron", "email": "ada@example.com"}
            ),
        )

    assert error.value.code == "CONTACT_DUPLICATE"
    assert session.added == []


async def test_a_patch_leaves_the_fields_it_does_not_mention_alone() -> None:
    actor_id = uuid.uuid4()
    contact = make_contact(actor_id)
    session = FakeSession()
    session.execute_queue = [[contact]]
    session.scalar_queue = [None]
    service = make_service(session)

    updated = await service.update(
        own(actor_id), contact.id, UpdateContactRequest.model_validate({"company": "Difference"})
    )

    assert updated.company == "Difference"
    # Absent fields are not the same as fields set to null.
    assert updated.email == "ada@example.com"
    assert updated.phone == "+380671234567"


async def test_a_patch_can_erase_a_channel() -> None:
    actor_id = uuid.uuid4()
    contact = make_contact(actor_id)
    session = FakeSession()
    session.execute_queue = [[contact]]
    session.scalar_queue = [None]
    service = make_service(session)

    updated = await service.update(
        own(actor_id), contact.id, UpdateContactRequest.model_validate({"email": None})
    )

    assert updated.email is None
    assert updated.phone == "+380671234567"


async def test_a_patch_may_not_erase_the_last_channel() -> None:
    actor_id = uuid.uuid4()
    contact = make_contact(actor_id)
    contact.email = None
    session = FakeSession()
    session.execute_queue = [[contact]]
    service = make_service(session)

    with pytest.raises(AppError) as error:
        await service.update(
            own(actor_id), contact.id, UpdateContactRequest.model_validate({"phone": None})
        )

    assert error.value.code == "CONTACT_CHANNEL_REQUIRED"
    assert error.value.status_code == 400


async def test_a_patch_records_both_sides_of_the_change() -> None:
    actor_id = uuid.uuid4()
    contact = make_contact(actor_id)
    session = FakeSession()
    session.execute_queue = [[contact]]
    session.scalar_queue = [None]
    audit = RecordingAudit()
    service = make_service(session, audit)

    await service.update(
        own(actor_id), contact.id, UpdateContactRequest.model_validate({"lastName": "Lovelace"})
    )

    changes = audit.events[0].changes
    assert audit.events[0].action == "contact.updated"
    assert changes["before"]["lastName"] == "Byron"
    assert changes["after"]["lastName"] == "Lovelace"


async def test_deleting_a_contact_only_marks_it() -> None:
    actor_id = uuid.uuid4()
    contact = make_contact(actor_id)
    session = FakeSession()
    session.execute_queue = [[contact]]
    audit = RecordingAudit()
    service = make_service(session, audit)

    await service.delete(own(actor_id), contact.id)

    # The row survives so history stays readable.
    assert contact.deleted_at is not None
    assert [event.action for event in audit.events] == ["contact.deleted"]


async def test_deleting_a_contact_of_another_owner_is_a_not_found() -> None:
    session = FakeSession()
    session.execute_queue = [[]]
    audit = RecordingAudit()
    service = make_service(session, audit)

    with pytest.raises(NotFoundError) as error:
        await service.delete(own(uuid.uuid4()), uuid.uuid4())

    assert error.value.code == "CONTACT_NOT_FOUND"
    assert audit.events == []
