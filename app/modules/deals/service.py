"""Deal rules.

Three of them are worth stating before the code. The stage of a deal changes
only through ``transition``; ``update`` never writes the column, so the machine
in ``transition.py`` cannot be walked around by an ordinary edit. Every write is
guarded by the version the caller read, and the guard lives in the ``WHERE``
clause of the statement itself, so two requests racing on the same deal cannot
both win. And a caller holding ``OWN`` has that narrowing applied to the query
rather than checked afterwards, which is what makes somebody else's deal come
back as missing instead of as forbidden.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Update, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.errors import AppError, ForbiddenError, NotFoundError, VersionConflictError
from app.core.filters import FilterBuilder
from app.core.paged_query import PagedQuery
from app.core.serializers import quantize_money
from app.db.enums import DealStage
from app.db.models.contact import Contact
from app.db.models.deal import Deal
from app.events.dispatch import announcer, publish_after_commit
from app.events.types import DomainEvent, DomainEventPublisher, NoopPublisher
from app.modules.audit import AuditEvent, AuditService
from app.modules.deals.schemas import (
    CreateDealRequest,
    DealListParams,
    DealOut,
    TransitionDealRequest,
    UpdateDealRequest,
)
from app.modules.deals.transition import (
    DEFAULT_DEAL_PROBABILITY,
    assert_deal_probability,
    assert_deal_stage_transition,
    closed_at_for_stage,
    resolve_transition_probability,
)
from app.modules.deals.types import (
    CONTACT_NOT_FOUND,
    DEAL_CONCURRENT_MODIFICATION,
    DEAL_CREATED,
    DEAL_DELETED,
    DEAL_ENTITY_TYPE,
    DEAL_NOT_FOUND,
    DEAL_STAGE_TRANSITIONED,
    DEAL_UPDATED,
    DEFAULT_CURRENCY,
    INVALID_DEAL_AMOUNT,
    INVALID_INITIAL_DEAL_STAGE,
    DealAccess,
    DealSortField,
)

#: Columns a client may sort by, under the names the client uses.
_SORTABLE: dict[DealSortField, InstrumentedAttribute[Any]] = {
    "createdAt": Deal.created_at,
    "updatedAt": Deal.updated_at,
    "title": Deal.title,
    "amount": Deal.amount,
    "probability": Deal.probability,
    "expectedCloseDate": Deal.expected_close_date,
}


def to_deal_out(deal: Deal) -> DealOut:
    """Renders a stored deal in the shape the API publishes."""
    return DealOut(
        id=deal.id,
        owner_id=deal.owner_id,
        contact_id=deal.contact_id,
        title=deal.title,
        stage=deal.stage,
        amount=deal.amount,
        currency=deal.currency,
        probability=deal.probability,
        version=deal.version,
        expected_close_date=deal.expected_close_date,
        closed_at=deal.closed_at,
        created_at=deal.created_at,
        updated_at=deal.updated_at,
    )


def _snapshot(deal: DealOut) -> dict[str, Any]:
    """A deal as a plain document, for the audit trail and the event stream."""
    return deal.model_dump(by_alias=True, mode="json")


def _assert_amount(amount: Decimal) -> None:
    """Guards the amount even though the schema already did.

    The schema is the client's contract; this is the domain's own invariant, and
    it also covers a service call that did not come through HTTP.
    """
    if not amount.is_finite() or amount < 0:
        raise AppError("Amount must be non-negative", 400, INVALID_DEAL_AMOUNT)


def _assert_initial_stage(stage: DealStage | None) -> None:
    if stage is not None and stage is not DealStage.LEAD:
        raise AppError("Deals must be created in the LEAD stage", 400, INVALID_INITIAL_DEAL_STAGE)


class _DealPage(PagedQuery[Deal, DealListParams, DealOut]):
    """One page of deals, scoped to what one caller may see."""

    def __init__(self, session: AsyncSession, access: DealAccess) -> None:
        super().__init__(session)
        self._access = access

    def _model(self) -> type[Deal]:
        return Deal

    def _build_filters(self, params: DealListParams) -> list[ColumnElement[bool]]:
        # A narrower grant pins the owner filter; the client's own `ownerId` is
        # ignored rather than merged, so it can never widen the result set.
        owner_id = self._access.actor_id if self._access.owned_only else params.owner_id

        return (
            FilterBuilder([Deal.deleted_at.is_(None)])
            .equals(Deal.owner_id, owner_id)
            .equals(Deal.contact_id, params.contact_id)
            .equals(Deal.stage, params.stage)
            .search(params.search, [Deal.title])
            .range(Deal.amount, params.min_amount, params.max_amount)
            .range(Deal.probability, params.min_probability, params.max_probability)
            .range(Deal.expected_close_date, params.expected_close_from, params.expected_close_to)
            .build()
        )

    def _order_by(self, params: DealListParams) -> Sequence[ColumnElement[Any]]:
        column = _SORTABLE[params.sort_by]
        primary = column.asc() if params.sort_order == "asc" else column.desc()
        # The id breaks ties: two deals sharing a timestamp would otherwise page
        # in whatever order the planner felt like.
        return (primary, Deal.id.asc())

    def _to_dto(self, row: Deal) -> DealOut:
        return to_deal_out(row)


class DealsService:
    """Reads and writes deals, and moves them through the pipeline."""

    def __init__(
        self,
        session: AsyncSession,
        events: DomainEventPublisher | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._events: DomainEventPublisher = events if events is not None else NoopPublisher()
        # The trail is written on the very session the change is written on, so
        # a rolled back deal cannot leave an entry claiming it happened.
        self._audit = audit if audit is not None else AuditService(session)

    async def list_deals(
        self, access: DealAccess, params: DealListParams
    ) -> tuple[list[DealOut], int]:
        """One page of deals, plus the size of the whole filtered set."""
        return await _DealPage(self._session, access).run(params)

    async def get_by_id(self, access: DealAccess, deal_id: uuid.UUID) -> DealOut:
        return to_deal_out(await self._require_active(access, deal_id))

    async def create(self, access: DealAccess, data: CreateDealRequest) -> DealOut:
        _assert_amount(data.amount)
        _assert_initial_stage(data.stage)

        owner_id = data.owner_id if data.owner_id is not None else access.actor_id
        self._ensure_may_assign(access, owner_id)

        stage = DealStage.LEAD
        probability = (
            data.probability if data.probability is not None else DEFAULT_DEAL_PROBABILITY[stage]
        )
        assert_deal_probability(stage, probability)
        await self._require_contact(access, data.contact_id)

        deal = Deal(
            id=uuid.uuid4(),
            owner_id=owner_id,
            contact_id=data.contact_id,
            title=data.title,
            stage=stage,
            amount=quantize_money(data.amount),
            currency=data.currency if data.currency is not None else DEFAULT_CURRENCY,
            probability=probability,
            version=1,
            expected_close_date=data.expected_close_date,
            closed_at=None,
        )
        self._session.add(deal)
        await self._session.flush()

        after = to_deal_out(deal)
        await self._record(access, DEAL_CREATED, deal.id, {"after": _snapshot(after)})
        self._announce(DEAL_CREATED, deal.id, access, {"after": _snapshot(after)})
        return after

    async def update(
        self, access: DealAccess, deal_id: uuid.UUID, data: UpdateDealRequest
    ) -> DealOut:
        """Edits a deal without touching its stage.

        ``stage`` is absent from the request shape on purpose: it is the one
        field whose value the client may propose but never set.
        """
        if data.amount is not None:
            _assert_amount(data.amount)

        existing = await self._require_active(access, deal_id)
        self._assert_version(existing.version, data.version)

        fields = data.model_fields_set
        owner_id = data.owner_id if data.owner_id is not None else existing.owner_id
        self._ensure_may_assign(access, owner_id)
        if "contact_id" in fields:
            await self._require_contact(access, data.contact_id)

        probability = data.probability if data.probability is not None else existing.probability
        assert_deal_probability(existing.stage, probability)

        values: dict[str, Any] = {}
        if data.owner_id is not None:
            values["owner_id"] = data.owner_id
        if "contact_id" in fields:
            values["contact_id"] = data.contact_id
        if data.title is not None:
            values["title"] = data.title
        if data.amount is not None:
            values["amount"] = quantize_money(data.amount)
        if data.currency is not None:
            values["currency"] = data.currency
        if data.probability is not None:
            values["probability"] = data.probability
        if "expected_close_date" in fields:
            values["expected_close_date"] = data.expected_close_date

        before = to_deal_out(existing)
        after = await self._write(access, deal_id, existing.stage, data.version, values)

        changes = {"before": _snapshot(before), "after": _snapshot(after)}
        await self._record(access, DEAL_UPDATED, deal_id, changes)
        self._announce(DEAL_UPDATED, deal_id, access, changes)
        return after

    async def transition(
        self, access: DealAccess, deal_id: uuid.UUID, data: TransitionDealRequest
    ) -> DealOut:
        """Moves a deal to the next stage the machine allows."""
        existing = await self._require_active(access, deal_id)
        self._assert_version(existing.version, data.version)
        assert_deal_stage_transition(existing.stage, data.stage)

        probability = resolve_transition_probability(
            data.stage, data.probability, existing.probability
        )
        assert_deal_probability(data.stage, probability)

        before = to_deal_out(existing)
        after = await self._write(
            access,
            deal_id,
            existing.stage,
            data.version,
            {
                "stage": data.stage,
                "probability": probability,
                # Reset rather than left alone: a stage that is not terminal has
                # no closing moment, and a stale one would misreport the deal.
                "closed_at": closed_at_for_stage(data.stage, datetime.now(tz=UTC)),
            },
        )

        changes = {"before": _snapshot(before), "after": _snapshot(after)}
        await self._record(access, DEAL_STAGE_TRANSITIONED, deal_id, changes)
        self._announce(
            DEAL_STAGE_TRANSITIONED,
            deal_id,
            access,
            {"from": str(before.stage), "to": str(after.stage), "after": _snapshot(after)},
        )
        return after

    async def delete(self, access: DealAccess, deal_id: uuid.UUID, version: int) -> None:
        """Hides a deal without losing it: the row stays, stamped as deleted."""
        existing = await self._require_active(access, deal_id)
        self._assert_version(existing.version, version)

        deleted_at = datetime.now(tz=UTC)
        before = to_deal_out(existing)
        statement = (
            update(Deal)
            .where(
                Deal.id == deal_id,
                Deal.version == version,
                Deal.deleted_at.is_(None),
                *self._owned(access),
            )
            .values(deleted_at=deleted_at, version=Deal.version + 1)
            # The identifier comes back only if the guarded row was the one
            # written; nothing returned means somebody else got there first.
            .returning(Deal.id)
            .execution_options(synchronize_session=False)
        )
        if (await self._session.execute(statement)).scalars().first() is None:
            raise VersionConflictError(
                "Deal was modified by another request", DEAL_CONCURRENT_MODIFICATION
            )

        changes = {
            "before": _snapshot(before),
            "after": {"deletedAt": deleted_at.isoformat(), "version": version + 1},
        }
        await self._record(access, DEAL_DELETED, deal_id, changes)
        self._announce(DEAL_DELETED, deal_id, access, {"id": str(deal_id)})

    async def _write(
        self,
        access: DealAccess,
        deal_id: uuid.UUID,
        stage: DealStage,
        version: int,
        values: dict[str, Any],
    ) -> DealOut:
        """Applies a guarded write and returns the row it produced.

        The guard repeats every condition the read established — version, stage,
        not deleted, and ownership — inside one statement. Re-checking in Python
        would leave a window in which another request could slip a change in
        between the read and the write, and the loser of that race must be told
        rather than silently overwrite the winner.
        """
        statement: Update = (
            update(Deal)
            .where(
                Deal.id == deal_id,
                Deal.version == version,
                Deal.stage == stage,
                Deal.deleted_at.is_(None),
                *self._owned(access),
            )
            .values(**values, version=Deal.version + 1)
            .returning(Deal)
            # `populate_existing` matters: the row just read is already in the
            # identity map, and without it the ORM would hand back that stale
            # instance instead of the values the database returned.
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        written = (await self._session.execute(statement)).scalars().first()
        if written is None:
            raise VersionConflictError(
                "Deal was modified by another request", DEAL_CONCURRENT_MODIFICATION
            )
        return to_deal_out(written)

    @staticmethod
    def _owned(access: DealAccess) -> list[ColumnElement[bool]]:
        return [Deal.owner_id == access.actor_id] if access.owned_only else []

    @staticmethod
    def _assert_version(actual: int, expected: int) -> None:
        if actual != expected:
            raise VersionConflictError(
                "Deal was modified by another request", DEAL_CONCURRENT_MODIFICATION
            )

    @staticmethod
    def _ensure_may_assign(access: DealAccess, owner_id: uuid.UUID) -> None:
        """Stops a narrow grant from handing a deal to somebody else.

        Forbidden rather than missing: the caller is naming a *user*, not
        addressing a deal, so there is no identifier to keep secret here.
        """
        if access.owned_only and owner_id != access.actor_id:
            raise ForbiddenError()

    async def _require_active(self, access: DealAccess, deal_id: uuid.UUID) -> Deal:
        statement = select(Deal).where(Deal.id == deal_id, Deal.deleted_at.is_(None))
        for criterion in self._owned(access):
            statement = statement.where(criterion)

        deal = (await self._session.execute(statement)).scalars().one_or_none()
        if deal is None:
            # Somebody else's deal is reported as missing, not as forbidden: a
            # narrower scope must not become a way to probe for ids.
            raise NotFoundError("Deal not found", DEAL_NOT_FOUND)
        return deal

    async def _require_contact(self, access: DealAccess, contact_id: uuid.UUID | None) -> None:
        """Refuses to attach a contact the caller cannot see."""
        if contact_id is None:
            return

        statement = select(Contact.id).where(Contact.id == contact_id, Contact.deleted_at.is_(None))
        if access.owned_only:
            statement = statement.where(Contact.owner_id == access.actor_id)

        if await self._session.scalar(statement) is None:
            raise NotFoundError("Contact not found", CONTACT_NOT_FOUND)

    async def _record(
        self, access: DealAccess, action: str, deal_id: uuid.UUID, changes: dict[str, Any]
    ) -> None:
        await self._audit.record(
            AuditEvent(
                actor_id=access.actor_id,
                action=action,
                entity_type=DEAL_ENTITY_TYPE,
                entity_id=deal_id,
                changes=changes,
                ip_address=access.ip_address,
            )
        )

    def _announce(
        self, event_type: str, deal_id: uuid.UUID, access: DealAccess, payload: Any
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
                    entity_type=DEAL_ENTITY_TYPE,
                    entity_id=str(deal_id),
                    actor_id=str(access.actor_id),
                    payload=payload,
                ),
            ),
        )
