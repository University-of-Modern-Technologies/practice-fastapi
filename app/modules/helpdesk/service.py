"""Ticket rules.

Three of them shape almost every method here. The status of a ticket changes
only through ``transition``; ``update`` never writes the column, so the machine
in ``transition.py`` cannot be walked around by an ordinary edit. Every write is
guarded by the version the caller read, and the guard lives in the ``WHERE``
clause of the statement itself, so two requests racing on the same ticket cannot
both win. And a caller holding ``OWN`` has that narrowing applied to the query
rather than checked afterwards, which is what makes somebody else's ticket come
back as missing instead of as forbidden.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, Update, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, VersionConflictError
from app.core.filters import FilterBuilder
from app.core.paged_query import PagedQuery
from app.db.enums import TicketPriority, TicketStatus
from app.db.models.contact import Contact
from app.db.models.ticket import Ticket, TicketStatusLog
from app.db.models.user import User
from app.events.dispatch import announcer, publish_after_commit
from app.events.types import DomainEvent, DomainEventPublisher, NoopPublisher
from app.modules.audit import AuditEvent, AuditService
from app.modules.helpdesk.schemas import (
    CreateTicketRequest,
    TicketListParams,
    TicketOut,
    TransitionTicketRequest,
    UpdateTicketRequest,
)
from app.modules.helpdesk.transition import (
    INITIAL_TICKET_STATUS,
    assert_ticket_status_transition,
    resolved_at_update,
)
from app.modules.helpdesk.types import (
    TICKET_ASSIGNEE_NOT_FOUND,
    TICKET_CONCURRENT_MODIFICATION,
    TICKET_CONTACT_NOT_FOUND,
    TICKET_CREATED,
    TICKET_DELETED,
    TICKET_DUPLICATE_NUMBER,
    TICKET_ENTITY_TYPE,
    TICKET_NOT_FOUND,
    TICKET_STATUS_TRANSITIONED,
    TICKET_UPDATED,
    TicketAccess,
    TicketSortField,
)

#: Columns a client may sort by, under the names the client uses. A lookup
#: rather than ``getattr``: only what is in this table can ever reach an
#: ``ORDER BY``.
_SORTABLE: dict[TicketSortField, InstrumentedAttribute[Any]] = {
    "createdAt": Ticket.created_at,
    "updatedAt": Ticket.updated_at,
    "openedAt": Ticket.opened_at,
    "priority": Ticket.priority,
    "status": Ticket.status,
}

_CONCURRENT_MESSAGE = "Ticket was modified by another request"
_NUMBER_UNAVAILABLE_MESSAGE = "Could not allocate a ticket number"

#: Digits in the human-readable part of a ticket number.
TICKET_NUMBER_DIGITS = 8
TICKET_NUMBER_PREFIX = "TKT-"
_TICKET_NUMBER_CEILING = 10**TICKET_NUMBER_DIGITS

#: How many numbers are drawn before a collision is reported to the caller.
TICKET_NUMBER_ATTEMPTS = 5


def generate_ticket_number() -> str:
    """Draws a ticket number of the published ``TKT-00000000`` shape.

    Drawn at random rather than counted up, and drawn in the service rather than
    defaulted in the database. Both halves of that are deliberate.

    A counter would read better but needs a row every writer has to serialize
    on, and the number is a label people quote on the phone rather than an
    ordering key — so uniqueness is left to the unique index and a collision is
    simply redrawn. Eight digits give a hundred million values, which puts a
    first collision well past any ticket count this desk will reach.

    ``secrets`` rather than ``random``: the number ends up in support email, and
    a sequence a stranger can continue is a way to address other people's
    tickets.
    """
    drawn = secrets.randbelow(_TICKET_NUMBER_CEILING)
    return f"{TICKET_NUMBER_PREFIX}{drawn:0{TICKET_NUMBER_DIGITS}d}"


def to_ticket_out(ticket: Ticket) -> TicketOut:
    """Renders a stored ticket in the shape the API publishes."""
    return TicketOut(
        id=ticket.id,
        number=ticket.number,
        subject=ticket.subject,
        body=ticket.body,
        channel=ticket.channel,
        status=ticket.status,
        priority=ticket.priority,
        contact_id=ticket.contact_id,
        assignee_id=ticket.assignee_id,
        owner_id=ticket.owner_id,
        opened_at=ticket.opened_at,
        resolved_at=ticket.resolved_at,
        version=ticket.version,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def _snapshot(ticket: TicketOut) -> dict[str, Any]:
    """A ticket as a plain document, for the audit trail and the event stream."""
    return ticket.model_dump(by_alias=True, mode="json")


def _is_ticket_number_conflict(error: IntegrityError) -> bool:
    """A collision on the drawn number is expected and is retried.

    The number is the only unique column a ticket carries, so any other
    integrity violation belongs to the caller's payload — a contact that
    vanished between the check and the insert, say — and is reported rather
    than redrawn.
    """
    return "number" in str(error.orig).lower()


class _TicketPage(PagedQuery[Ticket, TicketListParams, TicketOut]):
    """One page of tickets, scoped to what one caller may see."""

    def __init__(self, session: AsyncSession, access: TicketAccess) -> None:
        super().__init__(session)
        self._access = access

    def _model(self) -> type[Ticket]:
        return Ticket

    def _build_filters(self, params: TicketListParams) -> list[ColumnElement[bool]]:
        # A narrower grant pins the owner filter; the client's own `ownerId` is
        # ignored rather than merged, so it can never widen the result set.
        owner_id = self._access.actor_id if self._access.owned_only else params.owner_id

        return (
            FilterBuilder([Ticket.deleted_at.is_(None)])
            .equals(Ticket.owner_id, owner_id)
            .equals(Ticket.contact_id, params.contact_id)
            .equals(Ticket.assignee_id, params.assignee_id)
            .equals(Ticket.status, params.status)
            .equals(Ticket.channel, params.channel)
            .equals(Ticket.priority, params.priority)
            # The number is quoted back by the person reporting the problem far
            # more often than the subject is, so it is searchable alongside it.
            .search(params.search, [Ticket.subject, Ticket.number], escape=True)
            .range(Ticket.opened_at, params.opened_from, params.opened_to)
            .build()
        )

    def _order_by(self, params: TicketListParams) -> Sequence[ColumnElement[Any]]:
        column = _SORTABLE[params.sort_by]
        primary = column.asc() if params.sort_order == "asc" else column.desc()
        # The id breaks ties: two tickets sharing a status or a timestamp would
        # otherwise page in whatever order the planner felt like.
        return (primary, Ticket.id.asc())

    def _to_dto(self, row: Ticket) -> TicketOut:
        return to_ticket_out(row)


class HelpdeskService:
    """Reads and writes tickets, and moves them through their lifecycle."""

    def __init__(
        self,
        session: AsyncSession,
        events: DomainEventPublisher | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._events: DomainEventPublisher = events if events is not None else NoopPublisher()
        # The trail is written on the very session the change is written on, so
        # a rolled back ticket cannot leave an entry claiming it happened.
        self._audit = audit if audit is not None else AuditService(session)

    async def list_tickets(
        self, access: TicketAccess, params: TicketListParams
    ) -> tuple[list[TicketOut], int]:
        """One page of tickets, plus the size of the whole filtered set."""
        return await _TicketPage(self._session, access).run(params)

    async def get_by_id(self, access: TicketAccess, ticket_id: uuid.UUID) -> TicketOut:
        return to_ticket_out(await self._require_active(access, ticket_id))

    async def create(self, access: TicketAccess, data: CreateTicketRequest) -> TicketOut:
        owner_id = data.owner_id if data.owner_id is not None else access.actor_id
        self._ensure_may_assign(access, owner_id)
        await self._require_contact(access, data.contact_id)
        await self._require_assignee(data.assignee_id)

        ticket = await self._insert_ticket(data, owner_id)
        # The timestamps and the opening moment are produced by the server, so
        # they only exist on the instance once it has been read back.
        await self._session.refresh(ticket)

        # The opening entry is the only one whose `fromStatus` is null: it
        # records a ticket appearing rather than moving, and without it the log
        # would start halfway through the story.
        self._log_transition(access, ticket.id, None, ticket.status, None)

        after = to_ticket_out(ticket)
        await self._record(access, TICKET_CREATED, ticket.id, {"after": _snapshot(after)})
        self._announce(TICKET_CREATED, ticket.id, access, {"after": _snapshot(after)})
        return after

    async def update(
        self, access: TicketAccess, ticket_id: uuid.UUID, data: UpdateTicketRequest
    ) -> TicketOut:
        """Edits a ticket without touching its status.

        ``status`` is absent from the request shape on purpose: it is the one
        field whose value the client may propose but never set.
        """
        existing = await self._require_active(access, ticket_id)
        self._assert_version(existing.version, data.version)

        fields = data.model_fields_set
        owner_id = data.owner_id if data.owner_id is not None else existing.owner_id
        self._ensure_may_assign(access, owner_id)
        if "contact_id" in fields:
            await self._require_contact(access, data.contact_id)
        if "assignee_id" in fields:
            await self._require_assignee(data.assignee_id)

        values: dict[str, Any] = {}
        if data.owner_id is not None:
            values["owner_id"] = data.owner_id
        if "contact_id" in fields:
            values["contact_id"] = data.contact_id
        if "assignee_id" in fields:
            values["assignee_id"] = data.assignee_id
        if data.subject is not None:
            values["subject"] = data.subject
        if data.body is not None:
            values["body"] = data.body
        if data.channel is not None:
            values["channel"] = data.channel
        if data.priority is not None:
            values["priority"] = data.priority

        before = to_ticket_out(existing)
        after = await self._write(access, ticket_id, existing.status, data.version, values)

        changes = {"before": _snapshot(before), "after": _snapshot(after)}
        await self._record(access, TICKET_UPDATED, ticket_id, changes)
        self._announce(TICKET_UPDATED, ticket_id, access, changes)
        return after

    async def transition(
        self, access: TicketAccess, ticket_id: uuid.UUID, data: TransitionTicketRequest
    ) -> TicketOut:
        """Moves a ticket to the next status the machine allows."""
        existing = await self._require_active(access, ticket_id)
        self._assert_version(existing.version, data.version)
        assert_ticket_status_transition(existing.status, data.to_status)

        before = to_ticket_out(existing)
        after = await self._write(
            access,
            ticket_id,
            existing.status,
            data.version,
            # `resolved_at` is written, cleared or left entirely alone
            # depending on where the ticket is going; the machine decides
            # which, and an absent key is how "leave it alone" is spelled.
            {
                "status": data.to_status,
                **resolved_at_update(data.to_status, datetime.now(tz=UTC)),
            },
        )
        self._log_transition(access, ticket_id, before.status, after.status, data.note)

        changes = {"before": _snapshot(before), "after": _snapshot(after)}
        await self._record(access, TICKET_STATUS_TRANSITIONED, ticket_id, changes)
        self._announce(
            TICKET_STATUS_TRANSITIONED,
            ticket_id,
            access,
            {"from": str(before.status), "to": str(after.status), "after": _snapshot(after)},
        )
        return after

    async def delete(self, access: TicketAccess, ticket_id: uuid.UUID, version: int) -> None:
        """Hides a ticket without losing it: the row stays, stamped as deleted."""
        existing = await self._require_active(access, ticket_id)
        self._assert_version(existing.version, version)

        deleted_at = datetime.now(tz=UTC)
        before = to_ticket_out(existing)
        statement = (
            update(Ticket)
            .where(
                Ticket.id == ticket_id,
                Ticket.version == version,
                Ticket.deleted_at.is_(None),
                *self._owned(access),
            )
            .values(deleted_at=deleted_at, version=Ticket.version + 1)
            # The identifier comes back only if the guarded row was the one
            # written; nothing returned means somebody else got there first.
            .returning(Ticket.id)
            .execution_options(synchronize_session=False)
        )
        if (await self._session.execute(statement)).scalars().first() is None:
            raise VersionConflictError(_CONCURRENT_MESSAGE, TICKET_CONCURRENT_MODIFICATION)

        changes = {
            "before": _snapshot(before),
            "after": {"deletedAt": deleted_at.isoformat(), "version": version + 1},
        }
        await self._record(access, TICKET_DELETED, ticket_id, changes)
        self._announce(TICKET_DELETED, ticket_id, access, {"id": str(ticket_id)})

    async def _write(
        self,
        access: TicketAccess,
        ticket_id: uuid.UUID,
        status: TicketStatus,
        version: int,
        values: dict[str, Any],
    ) -> TicketOut:
        """Applies a guarded write and returns the row it produced.

        The guard repeats every condition the read established — version,
        status, not deleted, and ownership — inside one statement. Re-checking
        in Python would leave a window in which another request could slip a
        change in between the read and the write, and the loser of that race
        must be told rather than silently overwrite the winner.
        """
        statement: Update = (
            update(Ticket)
            .where(
                Ticket.id == ticket_id,
                Ticket.version == version,
                Ticket.status == status,
                Ticket.deleted_at.is_(None),
                *self._owned(access),
            )
            .values(**values, version=Ticket.version + 1)
            .returning(Ticket)
            # `populate_existing` matters: the row just read is already in the
            # identity map, and without it the ORM would hand back that stale
            # instance instead of the values the database returned.
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        written = (await self._session.execute(statement)).scalars().first()
        if written is None:
            raise VersionConflictError(_CONCURRENT_MESSAGE, TICKET_CONCURRENT_MODIFICATION)
        return to_ticket_out(written)

    def _log_transition(
        self,
        access: TicketAccess,
        ticket_id: uuid.UUID,
        from_status: TicketStatus | None,
        to_status: TicketStatus,
        note: str | None,
    ) -> None:
        """Appends one line to the ticket's own history.

        Written on the same session as the change it describes, for the same
        reason the audit entry is: a log that can outlive a rolled back
        transition is a log nobody can reason from.
        """
        self._session.add(
            TicketStatusLog(
                id=uuid.uuid4(),
                ticket_id=ticket_id,
                from_status=from_status,
                to_status=to_status,
                changed_by_id=access.actor_id,
                note=note,
            )
        )

    @staticmethod
    def _owned(access: TicketAccess) -> list[ColumnElement[bool]]:
        return [Ticket.owner_id == access.actor_id] if access.owned_only else []

    @staticmethod
    def _assert_version(actual: int, expected: int) -> None:
        if actual != expected:
            raise VersionConflictError(_CONCURRENT_MESSAGE, TICKET_CONCURRENT_MODIFICATION)

    @staticmethod
    def _ensure_may_assign(access: TicketAccess, owner_id: uuid.UUID) -> None:
        """Stops a narrow grant from handing a ticket to somebody else.

        Forbidden rather than missing: the caller is naming a *user*, not
        addressing a ticket, so there is no identifier to keep secret here.
        """
        if access.owned_only and owner_id != access.actor_id:
            raise ForbiddenError()

    async def _require_active(self, access: TicketAccess, ticket_id: uuid.UUID) -> Ticket:
        statement = select(Ticket).where(Ticket.id == ticket_id, Ticket.deleted_at.is_(None))
        for criterion in self._owned(access):
            statement = statement.where(criterion)

        ticket = (await self._session.execute(statement)).scalars().one_or_none()
        if ticket is None:
            # Somebody else's ticket is reported as missing, not as forbidden: a
            # narrower scope must not become a way to probe for ids.
            raise NotFoundError("Ticket not found", TICKET_NOT_FOUND)
        return ticket

    async def _require_contact(self, access: TicketAccess, contact_id: uuid.UUID | None) -> None:
        """Refuses to attach a contact the caller cannot see."""
        if contact_id is None:
            return

        statement = select(Contact.id).where(Contact.id == contact_id, Contact.deleted_at.is_(None))
        if access.owned_only:
            statement = statement.where(Contact.owner_id == access.actor_id)

        if await self._session.scalar(statement) is None:
            raise NotFoundError("Contact not found", TICKET_CONTACT_NOT_FOUND)

    async def _require_assignee(self, assignee_id: uuid.UUID | None) -> None:
        """Refuses to hand a ticket to an account that cannot work on it.

        Unlike the contact, the assignee is not narrowed by the caller's scope:
        a manager is a colleague, not a record the caller owns, so the only
        question here is whether the account exists and is still active.
        """
        if assignee_id is None:
            return

        statement = select(User.id).where(User.id == assignee_id, User.is_active.is_(True))
        if await self._session.scalar(statement) is None:
            raise NotFoundError("Assignee not found", TICKET_ASSIGNEE_NOT_FOUND)

    async def _insert_ticket(self, data: CreateTicketRequest, owner_id: uuid.UUID) -> Ticket:
        """Inserts the ticket, redrawing its number if that number was taken.

        The insert runs inside a savepoint so a collision can be retried without
        losing the surrounding transaction, which a failed statement would
        otherwise leave unusable. A caller who is unlucky five times running is
        told by name rather than silently handed a sixth draw.
        """
        for attempt in range(1, TICKET_NUMBER_ATTEMPTS + 1):
            ticket = Ticket(
                id=uuid.uuid4(),
                number=generate_ticket_number(),
                subject=data.subject,
                body=data.body,
                channel=data.channel,
                status=INITIAL_TICKET_STATUS,
                priority=data.priority if data.priority is not None else TicketPriority.NORMAL,
                owner_id=owner_id,
                contact_id=data.contact_id,
                assignee_id=data.assignee_id,
                version=1,
                resolved_at=None,
            )
            try:
                async with self._session.begin_nested():
                    self._session.add(ticket)
                    await self._session.flush()
            except IntegrityError as error:
                if not _is_ticket_number_conflict(error):
                    raise
                if attempt == TICKET_NUMBER_ATTEMPTS:
                    raise ConflictError(
                        _NUMBER_UNAVAILABLE_MESSAGE, TICKET_DUPLICATE_NUMBER
                    ) from error
            else:
                return ticket
        raise ConflictError(_NUMBER_UNAVAILABLE_MESSAGE, TICKET_DUPLICATE_NUMBER)

    async def _record(
        self, access: TicketAccess, action: str, ticket_id: uuid.UUID, changes: dict[str, Any]
    ) -> None:
        await self._audit.record(
            AuditEvent(
                actor_id=access.actor_id,
                action=action,
                entity_type=TICKET_ENTITY_TYPE,
                entity_id=ticket_id,
                changes=changes,
                ip_address=access.ip_address,
            )
        )

    def _announce(
        self, event_type: str, ticket_id: uuid.UUID, access: TicketAccess, payload: Any
    ) -> None:
        """Tells the secondary consumers what happened, once it has happened.

        Delivery waits for the session's commit: the request transaction closes
        after the handler returns, so announcing here would report a change that
        a later failure could still undo. A change that is written must then be
        reported as a success even if the event stream is unreachable, so a
        misbehaving publisher stays contained.
        """
        publish_after_commit(
            self._session,
            announcer(
                self._events,
                DomainEvent(
                    event_type=event_type,
                    entity_type=TICKET_ENTITY_TYPE,
                    entity_id=str(ticket_id),
                    actor_id=str(access.actor_id),
                    payload=payload,
                ),
            ),
        )
