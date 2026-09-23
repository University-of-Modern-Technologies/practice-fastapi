"""Contact rules.

Two of them shape almost every method here. The breadth of the caller's grant is
applied to the *query*, not to the result: a caller holding ``OWN`` must never
have somebody else's row selected in the first place, because a check performed
after the fact is one refactor away from being dropped. And removal is a soft
delete, so every read carries the same ``deleted_at IS NULL`` predicate — a
record that is gone must be gone for readers while staying readable for history.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.filters import FilterBuilder
from app.core.paged_query import PagedQuery
from app.db.models.contact import Contact
from app.modules.audit import AuditEvent, AuditService
from app.modules.contacts.schemas import (
    ContactListParams,
    ContactOut,
    CreateContactRequest,
    UpdateContactRequest,
)
from app.modules.contacts.types import (
    CONTACT_CHANNEL_REQUIRED,
    CONTACT_CREATED,
    CONTACT_DELETED,
    CONTACT_DUPLICATE,
    CONTACT_ENTITY_TYPE,
    CONTACT_NOT_FOUND,
    CONTACT_UPDATED,
    ContactAccess,
    ContactSortField,
)

_DUPLICATE_MESSAGE = "An active contact with this email or phone already exists"

#: The wire spelling of ``sortBy`` resolved to a column. A lookup rather than
#: ``getattr``: only what is in this table can ever reach an ``ORDER BY``.
_SORT_COLUMNS: dict[ContactSortField, InstrumentedAttribute[Any]] = {
    ContactSortField.CREATED_AT: Contact.created_at,
    ContactSortField.UPDATED_AT: Contact.updated_at,
    ContactSortField.FIRST_NAME: Contact.first_name,
    ContactSortField.LAST_NAME: Contact.last_name,
    ContactSortField.COMPANY: Contact.company,
}

#: A conjunction of predicates handed to ``where``. Named at module level
#: because inside the class body ``list`` is the name of a method.
type Criteria = list[ColumnElement[bool]]


def to_contact_out(contact: Contact) -> ContactOut:
    return ContactOut(
        id=contact.id,
        owner_id=contact.owner_id,
        first_name=contact.first_name,
        last_name=contact.last_name,
        email=contact.email,
        phone=contact.phone,
        company=contact.company,
        notes=contact.notes,
        created_at=contact.created_at,
        updated_at=contact.updated_at,
    )


def _snapshot(contact: ContactOut) -> dict[str, Any]:
    """The record as the audit trail records it."""
    return contact.model_dump(by_alias=True, mode="json")


def _visible(access: ContactAccess) -> Criteria:
    """The predicates that decide which rows exist for this caller."""
    criteria: Criteria = [Contact.deleted_at.is_(None)]
    if access.owned_only:
        criteria.append(Contact.owner_id == access.actor_id)
    return criteria


class _ContactPage(PagedQuery[Contact, ContactListParams, ContactOut]):
    """One page of contacts, scoped to what one caller may see."""

    def __init__(self, session: AsyncSession, access: ContactAccess) -> None:
        super().__init__(session)
        self._access = access

    def _model(self) -> type[Contact]:
        return Contact

    def _build_filters(self, params: ContactListParams) -> Criteria:
        criteria = _visible(self._access)

        # A narrow grant pins the owner; a wide one may filter by whichever
        # owner was asked for.
        owner_id = self._access.actor_id if self._access.owned_only else params.owner_id
        return (
            FilterBuilder(criteria)
            .equals(Contact.owner_id, owner_id)
            .search(
                params.search,
                [
                    Contact.first_name,
                    Contact.last_name,
                    Contact.email,
                    Contact.phone,
                    Contact.company,
                ],
                escape=True,
            )
            .build()
        )

    def _order_by(self, params: ContactListParams) -> tuple[ColumnElement[Any], ...]:
        column = _SORT_COLUMNS[params.sort_by]
        ordering = column.asc() if params.sort_order == "asc" else column.desc()
        # Tie-broken by id: rows sharing a company or a timestamp would
        # otherwise drift between pages.
        return (ordering, Contact.id.asc())

    def _to_dto(self, row: Contact) -> ContactOut:
        return to_contact_out(row)


class ContactsService:
    """Reads and writes contacts on one session."""

    def __init__(
        self,
        session: AsyncSession,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        # The trail is written on the caller's session on purpose: the business
        # change and its audit entry then commit, or roll back, as one.
        self._audit = audit if audit is not None else AuditService(session)

    async def list(
        self, access: ContactAccess, query: ContactListParams
    ) -> tuple[list[ContactOut], int]:
        """One page of contacts the caller is allowed to see."""
        return await _ContactPage(self._session, access).run(query)

    async def get_by_id(self, access: ContactAccess, contact_id: uuid.UUID) -> ContactOut:
        return to_contact_out(await self._require_active(access, contact_id))

    async def create(self, access: ContactAccess, data: CreateContactRequest) -> ContactOut:
        owner_id = data.owner_id if data.owner_id is not None else access.actor_id
        self._ensure_owner_allowed(access, owner_id)
        await self._require_no_duplicate(data.email, data.phone)

        contact = Contact(
            id=uuid.uuid4(),
            owner_id=owner_id,
            first_name=data.first_name,
            last_name=data.last_name,
            email=data.email,
            phone=data.phone,
            company=data.company,
            notes=data.notes,
        )
        self._session.add(contact)
        await self._flush()
        # The timestamps are produced by the server, so they only exist on the
        # instance once it has been read back.
        await self._session.refresh(contact)

        dto = to_contact_out(contact)
        await self._audit.record(
            AuditEvent(
                action=CONTACT_CREATED,
                entity_type=CONTACT_ENTITY_TYPE,
                entity_id=contact.id,
                actor_id=access.actor_id,
                changes={"after": _snapshot(dto)},
                ip_address=access.ip_address,
            )
        )
        return dto

    async def update(
        self, access: ContactAccess, contact_id: uuid.UUID, data: UpdateContactRequest
    ) -> ContactOut:
        contact = await self._require_active(access, contact_id)
        before = _snapshot(to_contact_out(contact))
        fields = data.model_fields_set

        owner_id = data.owner_id if data.owner_id is not None else contact.owner_id
        self._ensure_owner_allowed(access, owner_id)

        # Read through the patch: what the record will look like decides whether
        # it still has a channel, and whether that channel is already taken.
        email = data.email if "email" in fields else contact.email
        phone = data.phone if "phone" in fields else contact.phone
        if not email and not phone:
            raise AppError("Email or phone is required", 400, CONTACT_CHANNEL_REQUIRED)
        await self._require_no_duplicate(email, phone, exclude_id=contact_id)

        if "owner_id" in fields and data.owner_id is not None:
            contact.owner_id = data.owner_id
        if "first_name" in fields and data.first_name is not None:
            contact.first_name = data.first_name
        if "last_name" in fields and data.last_name is not None:
            contact.last_name = data.last_name
        if "email" in fields:
            contact.email = data.email
        if "phone" in fields:
            contact.phone = data.phone
        if "company" in fields:
            contact.company = data.company
        if "notes" in fields:
            contact.notes = data.notes

        await self._flush()
        await self._session.refresh(contact)

        dto = to_contact_out(contact)
        after = _snapshot(dto)
        await self._audit.record(
            AuditEvent(
                action=CONTACT_UPDATED,
                entity_type=CONTACT_ENTITY_TYPE,
                entity_id=contact_id,
                actor_id=access.actor_id,
                changes={"before": before, "after": after},
                ip_address=access.ip_address,
            )
        )
        return dto

    async def delete(self, access: ContactAccess, contact_id: uuid.UUID) -> None:
        """Marks a contact as deleted, keeping the row for history."""
        contact = await self._require_active(access, contact_id)
        before = _snapshot(to_contact_out(contact))

        deleted_at = datetime.now(tz=UTC)
        contact.deleted_at = deleted_at
        await self._flush()

        await self._audit.record(
            AuditEvent(
                action=CONTACT_DELETED,
                entity_type=CONTACT_ENTITY_TYPE,
                entity_id=contact_id,
                actor_id=access.actor_id,
                changes={"before": before, "after": {"deletedAt": deleted_at}},
                ip_address=access.ip_address,
            )
        )

    @staticmethod
    def _ensure_owner_allowed(access: ContactAccess, owner_id: uuid.UUID) -> None:
        """Only a caller who sees everything may hand a contact to someone else."""
        if access.owned_only and owner_id != access.actor_id:
            raise ForbiddenError()

    async def _require_active(self, access: ContactAccess, contact_id: uuid.UUID) -> Contact:
        result = await self._session.execute(
            select(Contact).where(Contact.id == contact_id, *_visible(access))
        )
        contact = result.scalars().one_or_none()
        if contact is None:
            # Somebody else's record is reported as missing rather than as
            # forbidden: a 403 would confirm the id exists, which turns the
            # endpoint into an enumeration oracle.
            raise NotFoundError("Contact not found", CONTACT_NOT_FOUND)
        return contact

    async def _require_no_duplicate(
        self, email: str | None, phone: str | None, exclude_id: uuid.UUID | None = None
    ) -> None:
        """Refuses a second live contact reachable at the same address or number.

        Deleted rows are ignored on purpose: their channels are free again, and
        the check spans every owner because a duplicate is a duplicate for the
        organization, not for one manager.
        """
        channels: Criteria = []
        if email:
            channels.append(func.lower(Contact.email) == email.lower())
        if phone:
            channels.append(Contact.phone == phone)
        if not channels:
            return

        criteria: Criteria = [Contact.deleted_at.is_(None), or_(*channels)]
        if exclude_id is not None:
            criteria.append(Contact.id != exclude_id)

        if await self._session.scalar(select(Contact.id).where(*criteria)) is not None:
            raise ConflictError(_DUPLICATE_MESSAGE, CONTACT_DUPLICATE)

    async def _flush(self) -> None:
        """Surfaces a constraint violation as the conflict it represents.

        The check above races with a concurrent writer; the database is what
        settles it, and its error has to reach the client in the same shape.
        """
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise ConflictError(_DUPLICATE_MESSAGE, CONTACT_DUPLICATE) from error
