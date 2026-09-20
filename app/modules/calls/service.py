"""Call rules.

Three of them shape almost every method here.

A call is never authored: it is imported. ``sync`` is the only way one comes
into existence, and it is idempotent by construction — ``external_id`` is unique
and is checked against what is already on file before a single row is inserted,
so running the same batch twice creates nothing the second time. That check
deliberately ignores the soft-delete flag: a call somebody deleted must stay
deleted, and re-importing it would be a way to undo a deletion by accident.

Every edit is guarded by the version the caller read, and the guard lives in the
``WHERE`` clause of the statement itself, so two requests racing on the same
call cannot both win.

And a caller holding ``OWN`` has that narrowing applied to the query rather than
checked afterwards. What ``OWN`` means when a call has no owner at all is the
one decision this module could not inherit; it is written down on
``CallAccess.owned_only``, and every predicate below is the literal consequence
of it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Update, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.errors import ForbiddenError, NotFoundError, VersionConflictError
from app.core.filters import FilterBuilder
from app.core.paged_query import PagedQuery
from app.db.models.call import Call
from app.db.models.contact import Contact
from app.db.models.deal import Deal
from app.events.dispatch import announcer, publish_after_commit
from app.events.types import DomainEvent, DomainEventPublisher, NoopPublisher
from app.modules.audit import AuditEvent, AuditService
from app.modules.calls.provider import (
    CallProvider,
    CallProviderFetchRequest,
    ProviderCall,
)
from app.modules.calls.provider_factory import DEFAULT_CALL_SYNC_BATCH_SIZE
from app.modules.calls.schemas import (
    CallListParams,
    CallOut,
    CallRecordingOut,
    LinkCallRequest,
    SyncCallsOut,
    UpdateCallRequest,
)
from app.modules.calls.types import (
    CALL_CONCURRENT_MODIFICATION,
    CALL_CONTACT_NOT_FOUND,
    CALL_CREATED,
    CALL_DEAL_NOT_FOUND,
    CALL_DELETED,
    CALL_ENTITY_TYPE,
    CALL_LINKED,
    CALL_NOT_FOUND,
    CALL_RECORDING_UNAVAILABLE,
    CALL_UPDATED,
    CallAccess,
    CallSortField,
)

__all__ = ["RECORDING_URL_TTL_SECONDS", "CallsService", "to_call_out"]

#: Columns a client may sort by, under the names the client uses. A lookup
#: rather than ``getattr``: only what is in this table can ever reach an
#: ``ORDER BY``.
_SORTABLE: dict[CallSortField, InstrumentedAttribute[Any]] = {
    "startedAt": Call.started_at,
    "createdAt": Call.created_at,
    "durationSeconds": Call.duration_seconds,
}

_CONCURRENT_MESSAGE = "Call was modified by another request"

#: How long a recording link stays playable. Fifteen minutes is long enough to
#: open a player and listen, short enough that a link copied out of a browser
#: history is worthless by the time anybody else finds it.
RECORDING_URL_TTL_SECONDS = 900


def to_call_out(call: Call) -> CallOut:
    """Renders a stored call in the shape the API publishes."""
    return CallOut(
        id=call.id,
        external_id=call.external_id,
        direction=call.direction,
        disposition=call.disposition,
        from_number=call.from_number,
        to_number=call.to_number,
        started_at=call.started_at,
        duration_seconds=call.duration_seconds,
        contact_id=call.contact_id,
        deal_id=call.deal_id,
        owner_id=call.owner_id,
        recording_url=call.recording_url,
        notes=call.notes,
        version=call.version,
        created_at=call.created_at,
        updated_at=call.updated_at,
    )


def _snapshot(call: CallOut) -> dict[str, Any]:
    """A call as a plain document, for the audit trail and the event stream."""
    return call.model_dump(by_alias=True, mode="json")


def _is_external_id_conflict(error: IntegrityError) -> bool:
    """Whether the insert lost a race on the provider's identifier.

    ``external_id`` is the only unique column a call carries, so any other
    integrity violation belongs elsewhere — a foreign key that vanished, a
    check that failed — and is raised rather than quietly counted as a skip.
    """
    return "external_id" in str(error.orig).lower()


class _CallPage(PagedQuery[Call, CallListParams, CallOut]):
    """One page of calls, scoped to what one caller may see."""

    def __init__(self, session: AsyncSession, access: CallAccess) -> None:
        super().__init__(session)
        self._access = access

    def _model(self) -> type[Call]:
        return Call

    def _build_filters(self, params: CallListParams) -> list[ColumnElement[bool]]:
        # A narrower grant pins the owner filter; the client's own `ownerId` is
        # ignored rather than merged, so it can never widen the result set.
        owner_id = self._access.actor_id if self._access.owned_only else params.owner_id

        builder = (
            FilterBuilder([Call.deleted_at.is_(None)])
            .equals(Call.owner_id, owner_id)
            .equals(Call.contact_id, params.contact_id)
            .equals(Call.deal_id, params.deal_id)
            .equals(Call.direction, params.direction)
            .equals(Call.disposition, params.disposition)
            # A number read off a phone screen and a note somebody typed are
            # the two things anybody actually searches a call log by. The
            # provider's own identifier is not among them: nobody quotes it.
            .search(
                params.search,
                [Call.from_number, Call.to_number, Call.notes],
                escape=True,
            )
            .range(Call.started_at, params.started_from, params.started_to)
        )
        if params.has_contact is not None:
            # `IS NULL` rather than `= NULL`: this filter asks about absence,
            # which is the one comparison SQL refuses to answer with equality.
            builder.add(
                Call.contact_id.is_not(None) if params.has_contact else Call.contact_id.is_(None)
            )
        return builder.build()

    def _order_by(self, params: CallListParams) -> Sequence[ColumnElement[Any]]:
        column = _SORTABLE[params.sort_by]
        primary = column.asc() if params.sort_order == "asc" else column.desc()
        # The id breaks ties: two calls sharing a duration or an instant would
        # otherwise page in whatever order the planner felt like.
        return (primary, Call.id.asc())

    def _to_dto(self, row: Call) -> CallOut:
        return to_call_out(row)


class CallsService:
    """Imports calls from the provider, and lets people attach meaning to them."""

    def __init__(
        self,
        session: AsyncSession,
        provider: CallProvider,
        events: DomainEventPublisher | None = None,
        audit: AuditService | None = None,
        sync_batch_size: int = DEFAULT_CALL_SYNC_BATCH_SIZE,
    ) -> None:
        self._session = session
        self._provider = provider
        self._sync_batch_size = sync_batch_size
        self._events: DomainEventPublisher = events if events is not None else NoopPublisher()
        # The trail is written on the very session the change is written on, so
        # a rolled back import cannot leave entries claiming it happened.
        self._audit = audit if audit is not None else AuditService(session)

    async def list_calls(
        self, access: CallAccess, params: CallListParams
    ) -> tuple[list[CallOut], int]:
        """One page of calls, plus the size of the whole filtered set."""
        return await _CallPage(self._session, access).run(params)

    async def get_by_id(self, access: CallAccess, call_id: uuid.UUID) -> CallOut:
        return to_call_out(await self._require_active(access, call_id))

    async def sync(self, access: CallAccess) -> SyncCallsOut:
        """Pulls a batch from the provider and files whatever is new.

        Idempotent by identity rather than by bookkeeping: the provider's
        ``external_id`` is unique in this table, and everything that is already
        on file is skipped before an insert is attempted. Nothing here depends
        on when the previous sync ran, so a repeated batch, an overlapping
        window and a batch replayed after a crash all converge on the same
        result.

        The batch is deduplicated against itself first. A provider that lists
        the same call twice is reporting one call, and the second mention is
        counted as skipped rather than treated as a collision — it is not a
        contradiction, just a repetition.

        A duplicate is never an error anywhere in this method, which is why the
        rows go in one savepoint at a time rather than in one statement. The
        lookup above races with a concurrent sync, and in PostgreSQL a unique
        violation poisons the whole transaction: batched, a single call that
        somebody else imported a second earlier would take the entire import
        down with it. One savepoint per row means the collision rolls back
        exactly that row, is counted as skipped, and its neighbours are kept.

        Imported calls arrive owned by nobody. The provider knows telephone
        numbers, not which colleague the conversation belongs to, and guessing
        an owner from whoever happened to press "sync" would put a record into
        one person's view on the strength of an accident.
        """
        batch = await self._provider.fetch_calls(
            CallProviderFetchRequest(limit=self._sync_batch_size)
        )
        fetched = len(batch)

        unique = self._deduplicate(batch)
        known = await self._existing_external_ids(unique)

        staged: list[Call] = []
        for item in unique.values():
            if item.external_id in known:
                continue
            row = await self._insert(item)
            if row is not None:
                staged.append(row)

        for row in staged:
            created = to_call_out(row)
            changes = {"after": _snapshot(created)}
            await self._record(access, CALL_CREATED, created.id, changes)
            self._announce(CALL_CREATED, created.id, access, changes)

        return SyncCallsOut(fetched=fetched, created=len(staged), skipped=fetched - len(staged))

    async def update(
        self, access: CallAccess, call_id: uuid.UUID, data: UpdateCallRequest
    ) -> CallOut:
        """Edits what the call means to this organization, and nothing else.

        The provider's own facts — direction, disposition, numbers, duration —
        are absent from the request shape: they describe traffic that already
        happened, and an API that let them be rewritten would be an API for
        falsifying a call log.
        """
        existing = await self._require_active(access, call_id)
        self._assert_version(existing.version, data.version)
        fields = data.model_fields_set

        values: dict[str, Any] = {}
        if "owner_id" in fields:
            self._ensure_may_assign(access, data.owner_id)
            values["owner_id"] = data.owner_id
        if "contact_id" in fields:
            await self._require_contact(access, data.contact_id)
            values["contact_id"] = data.contact_id
        if "deal_id" in fields:
            await self._require_deal(access, data.deal_id)
            values["deal_id"] = data.deal_id
        if "notes" in fields:
            values["notes"] = data.notes

        before = to_call_out(existing)
        after = await self._write(access, call_id, data.version, values)

        changes = {"before": _snapshot(before), "after": _snapshot(after)}
        await self._record(access, CALL_UPDATED, call_id, changes)
        self._announce(CALL_UPDATED, call_id, access, changes)
        return after

    async def link(self, access: CallAccess, call_id: uuid.UUID, data: LinkCallRequest) -> CallOut:
        """Attaches the call to the records it belongs to.

        Deliberately its own endpoint rather than a flavour of ``PATCH``:
        attaching a call to a customer is the act this module exists for, it is
        the one an operator performs dozens of times a shift, and it is worth
        being able to find in an audit trail as ``call.linked`` rather than as
        one more generic edit.
        """
        existing = await self._require_active(access, call_id)
        self._assert_version(existing.version, data.version)
        fields = data.model_fields_set

        values: dict[str, Any] = {}
        if "contact_id" in fields:
            await self._require_contact(access, data.contact_id)
            values["contact_id"] = data.contact_id
        if "deal_id" in fields:
            await self._require_deal(access, data.deal_id)
            values["deal_id"] = data.deal_id

        before = to_call_out(existing)
        after = await self._write(access, call_id, data.version, values)

        changes = {"before": _snapshot(before), "after": _snapshot(after)}
        await self._record(access, CALL_LINKED, call_id, changes)
        self._announce(CALL_LINKED, call_id, access, changes)
        return after

    async def get_recording(self, access: CallAccess, call_id: uuid.UUID) -> CallRecordingOut:
        """Hands back a short-lived link to the recording, if there is one.

        A missing recording is an ordinary outcome, not a fault: a call nobody
        answered has nothing to listen to, and some providers keep audio only
        for a retention window. It is reported as 404 with its own code so a
        client can tell "this call has no audio" from "there is no such call".

        Nothing is asked of the provider here. The link the sync already stored
        is what is published, so a provider having a bad afternoon cannot take
        the read path down with it.
        """
        call = await self._require_active(access, call_id)
        if not call.recording_url:
            raise NotFoundError("This call has no recording", CALL_RECORDING_UNAVAILABLE)

        expires_at = datetime.now(tz=UTC) + timedelta(seconds=RECORDING_URL_TTL_SECONDS)
        return CallRecordingOut(url=call.recording_url, expires_at=expires_at)

    async def delete(self, access: CallAccess, call_id: uuid.UUID, version: int) -> None:
        """Hides a call without losing it: the row stays, stamped as deleted.

        The row stays for a second reason beyond history. ``external_id`` is
        unique across deleted rows too, so the record left behind is what keeps
        the next sync from quietly re-importing a call somebody removed on
        purpose.
        """
        existing = await self._require_active(access, call_id)
        self._assert_version(existing.version, version)

        deleted_at = datetime.now(tz=UTC)
        before = to_call_out(existing)
        statement = (
            update(Call)
            .where(
                Call.id == call_id,
                Call.version == version,
                Call.deleted_at.is_(None),
                *self._owned(access),
            )
            .values(deleted_at=deleted_at, version=Call.version + 1)
            # The identifier comes back only if the guarded row was the one
            # written; nothing returned means somebody else got there first.
            .returning(Call.id)
            .execution_options(synchronize_session=False)
        )
        if (await self._session.execute(statement)).scalars().first() is None:
            raise VersionConflictError(_CONCURRENT_MESSAGE, CALL_CONCURRENT_MODIFICATION)

        changes = {
            "before": _snapshot(before),
            "after": {"deletedAt": deleted_at.isoformat(), "version": version + 1},
        }
        await self._record(access, CALL_DELETED, call_id, changes)
        self._announce(CALL_DELETED, call_id, access, {"id": str(call_id)})

    @staticmethod
    def _deduplicate(batch: Iterable[ProviderCall]) -> dict[str, ProviderCall]:
        """Collapses a batch onto its identifiers, keeping the first mention.

        The first rather than the last on purpose: a provider that repeats a
        call is repeating itself, and preferring the later copy would make the
        import depend on the order of a list nobody promised to order.
        """
        unique: dict[str, ProviderCall] = {}
        for item in batch:
            unique.setdefault(item.external_id, item)
        return unique

    async def _existing_external_ids(self, unique: dict[str, ProviderCall]) -> set[str]:
        """Which of these calls are already on file — deleted ones included.

        One query for the whole batch rather than one per call: a sync that
        issues a lookup per row turns a routine import into a few hundred round
        trips, and the set it builds is the same either way.

        Soft-deleted rows count as present. They still hold the unique
        ``external_id``, so an insert would fail on them anyway — and, more to
        the point, a call somebody deleted deliberately must not reappear
        because the provider mentioned it again.
        """
        if not unique:
            return set()

        result = await self._session.execute(
            select(Call.external_id).where(Call.external_id.in_(unique.keys()))
        )
        return set(result.scalars().all())

    async def _insert(self, item: ProviderCall) -> Call | None:
        """Files one imported call, or reports that somebody beat us to it.

        Every association is left empty: the switchboard knows telephone
        numbers, not which contact, deal or colleague they turned out to be
        about.

        The insert runs inside a savepoint so a collision can be absorbed
        without losing the surrounding transaction, which a failed statement
        would otherwise leave unusable. ``None`` means the identifier was taken
        between the lookup and the write — a concurrent sync that got there
        first, which is the ordinary outcome this module is built around rather
        than a failure to report.
        """
        call = Call(
            id=uuid.uuid4(),
            external_id=item.external_id,
            direction=item.direction,
            disposition=item.disposition,
            from_number=item.from_number,
            to_number=item.to_number,
            started_at=item.started_at,
            duration_seconds=item.duration_seconds,
            owner_id=None,
            contact_id=None,
            deal_id=None,
            recording_url=item.recording_url,
            notes=None,
            version=1,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(call)
                await self._session.flush()
        except IntegrityError as error:
            if not _is_external_id_conflict(error):
                raise
            return None
        # The timestamps are produced by the server, so they only exist on the
        # instance once it has been read back.
        await self._session.refresh(call)
        return call

    async def _write(
        self,
        access: CallAccess,
        call_id: uuid.UUID,
        version: int,
        values: dict[str, Any],
    ) -> CallOut:
        """Applies a guarded write and returns the row it produced.

        The guard repeats every condition the read established — version, not
        deleted, and ownership — inside one statement. Re-checking in Python
        would leave a window in which another request could slip a change in
        between the read and the write, and the loser of that race must be told
        rather than silently overwrite the winner.
        """
        statement: Update = (
            update(Call)
            .where(
                Call.id == call_id,
                Call.version == version,
                Call.deleted_at.is_(None),
                *self._owned(access),
            )
            .values(**values, version=Call.version + 1)
            .returning(Call)
            # `populate_existing` matters: the row just read is already in the
            # identity map, and without it the ORM would hand back that stale
            # instance instead of the values the database returned.
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        written = (await self._session.execute(statement)).scalars().first()
        if written is None:
            raise VersionConflictError(_CONCURRENT_MESSAGE, CALL_CONCURRENT_MODIFICATION)
        return to_call_out(written)

    @staticmethod
    def _owned(access: CallAccess) -> list[ColumnElement[bool]]:
        """The ownership narrowing, as a predicate rather than as a check.

        ``owner_id = :actor`` excludes the unowned rows by itself, because
        ``NULL`` compares equal to nothing — which is the behaviour
        ``CallAccess.owned_only`` describes, arrived at without a special case.
        """
        return [Call.owner_id == access.actor_id] if access.owned_only else []

    @staticmethod
    def _assert_version(actual: int, expected: int) -> None:
        if actual != expected:
            raise VersionConflictError(_CONCURRENT_MESSAGE, CALL_CONCURRENT_MODIFICATION)

    @staticmethod
    def _ensure_may_assign(access: CallAccess, owner_id: uuid.UUID | None) -> None:
        """Stops a narrow grant from handing a call to somebody other than itself.

        ``null`` is refused for the same reason a colleague's id is: releasing a
        call back to "nobody" puts it beyond the caller's own view, which is
        giving it away by another name. A wide grant may do both.

        Forbidden rather than missing: the caller is naming a *user*, not
        addressing a call, so there is no identifier to keep secret here.
        """
        if access.owned_only and owner_id != access.actor_id:
            raise ForbiddenError()

    async def _require_active(self, access: CallAccess, call_id: uuid.UUID) -> Call:
        statement = select(Call).where(Call.id == call_id, Call.deleted_at.is_(None))
        for criterion in self._owned(access):
            statement = statement.where(criterion)

        call = (await self._session.execute(statement)).scalars().one_or_none()
        if call is None:
            # Somebody else's call is reported as missing, not as forbidden: a
            # narrower scope must not become a way to probe for ids.
            raise NotFoundError("Call not found", CALL_NOT_FOUND)
        return call

    async def _require_contact(self, access: CallAccess, contact_id: uuid.UUID | None) -> None:
        """Refuses to attach a contact the caller cannot see.

        ``None`` is the request to detach, which needs no lookup: an operator
        who linked the wrong customer has to be able to undo it.
        """
        if contact_id is None:
            return

        statement = select(Contact.id).where(Contact.id == contact_id, Contact.deleted_at.is_(None))
        if access.owned_only:
            statement = statement.where(Contact.owner_id == access.actor_id)

        if await self._session.scalar(statement) is None:
            raise NotFoundError("Contact not found", CALL_CONTACT_NOT_FOUND)

    async def _require_deal(self, access: CallAccess, deal_id: uuid.UUID | None) -> None:
        """Refuses to attach a deal the caller cannot see."""
        if deal_id is None:
            return

        statement = select(Deal.id).where(Deal.id == deal_id, Deal.deleted_at.is_(None))
        if access.owned_only:
            statement = statement.where(Deal.owner_id == access.actor_id)

        if await self._session.scalar(statement) is None:
            raise NotFoundError("Deal not found", CALL_DEAL_NOT_FOUND)

    async def _record(
        self, access: CallAccess, action: str, call_id: uuid.UUID, changes: dict[str, Any]
    ) -> None:
        await self._audit.record(
            AuditEvent(
                actor_id=access.actor_id,
                action=action,
                entity_type=CALL_ENTITY_TYPE,
                entity_id=call_id,
                changes=changes,
                ip_address=access.ip_address,
            )
        )

    def _announce(
        self, event_type: str, call_id: uuid.UUID, access: CallAccess, payload: Any
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
                    entity_type=CALL_ENTITY_TYPE,
                    entity_id=str(call_id),
                    actor_id=str(access.actor_id),
                    payload=payload,
                ),
            ),
        )
