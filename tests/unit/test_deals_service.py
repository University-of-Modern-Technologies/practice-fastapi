"""Deal rules: the stage machine, optimistic locking and the narrow grant.

The session is a scripted stand-in rather than a database, so what is asserted
here is the *statement* the service builds — which is where the version guard
and the ownership narrowing actually live.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError, VersionConflictError
from app.db.enums import DealStage, PermissionScope
from app.db.models.audit import AuditLog
from app.db.models.deal import Deal
from app.events.types import DomainEvent
from app.modules.deals.schemas import (
    CreateDealRequest,
    DealListParams,
    TransitionDealRequest,
    UpdateDealRequest,
)
from app.modules.deals.service import DealsService
from app.modules.deals.types import (
    DEAL_CREATED,
    DEAL_DELETED,
    DEAL_NOT_FOUND,
    DEAL_STAGE_TRANSITIONED,
    DEAL_UPDATED,
    INVALID_DEAL_STAGE_TRANSITION,
    INVALID_INITIAL_DEAL_STAGE,
    DealAccess,
)

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)
ACTOR_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
DEAL_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")

OWN_ACCESS = DealAccess(actor_id=ACTOR_ID, scope=PermissionScope.OWN, ip_address="203.0.113.7")
ALL_ACCESS = DealAccess(actor_id=ACTOR_ID, scope=PermissionScope.ALL)

#: Statements are compiled against the dialect the application actually runs on,
#: so what is asserted is the SQL the database would receive.
PG_DIALECT = cast("Any", postgresql).dialect()


class FakeScalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return list(self._values)

    def first(self) -> Any:
        return self._values[0] if self._values else None

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
        """Stands in for the server defaults a real flush would fill in."""
        self.flushes += 1
        for row in self.added:
            if isinstance(row, Deal) and getattr(row, "created_at", None) is None:
                row.created_at = NOW
                row.updated_at = NOW
            if isinstance(row, AuditLog) and getattr(row, "id", None) is None:
                row.id = uuid.uuid4()
                row.created_at = NOW


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.published.append(event)


class BrokenPublisher:
    def publish(self, _event: DomainEvent) -> None:
        message = "event stream unreachable"
        raise RuntimeError(message)


def make_deal(**overrides: Any) -> Deal:
    values: dict[str, Any] = {
        "id": DEAL_ID,
        "owner_id": ACTOR_ID,
        "contact_id": None,
        "title": "Opportunity",
        "stage": DealStage.LEAD,
        "amount": Decimal("1000.00"),
        "currency": "USD",
        "probability": 10,
        "version": 1,
        "expected_close_date": None,
        "closed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        "deleted_at": None,
    }
    return Deal(**(values | overrides))


def make_service(session: FakeSession, publisher: Any = None) -> DealsService:
    return DealsService(cast("AsyncSession", session), publisher)


def audit_actions(session: FakeSession) -> list[str]:
    return [row.action for row in session.added if isinstance(row, AuditLog)]


def where_of(statement: Any) -> tuple[str, dict[str, Any]]:
    compiled = statement.whereclause.compile(dialect=PG_DIALECT)
    return str(compiled), dict(compiled.params)


def set_clause_of(statement: Any) -> tuple[str, dict[str, Any]]:
    compiled = statement.compile(dialect=PG_DIALECT)
    return str(compiled).split(" WHERE ")[0], dict(compiled.params)


async def test_a_deal_cannot_be_created_past_the_start_of_the_pipeline() -> None:
    session = FakeSession()
    # Built without validation on purpose: the rule has to hold even if the
    # schema that normally enforces it is bypassed.
    fields: dict[str, Any] = {
        "owner_id": None,
        "contact_id": None,
        "title": "Closed opportunity",
        "stage": DealStage.WON,
        "amount": Decimal("1000.00"),
        "currency": None,
        "probability": None,
        "expected_close_date": None,
    }
    data = CreateDealRequest.model_construct(**fields)

    with pytest.raises(AppError) as error:
        await make_service(session).create(OWN_ACCESS, data)

    assert error.value.status_code == 400
    assert error.value.code == INVALID_INITIAL_DEAL_STAGE
    assert session.added == []


async def test_a_new_deal_starts_as_a_lead_and_is_recorded() -> None:
    session = FakeSession()
    publisher = RecordingPublisher()
    data = CreateDealRequest.model_validate({"title": "Opportunity", "amount": "1000.5"})

    created = await make_service(session, publisher).create(OWN_ACCESS, data)

    stored = next(row for row in session.added if isinstance(row, Deal))
    assert stored.stage is DealStage.LEAD
    assert stored.owner_id == ACTOR_ID
    assert stored.currency == "USD"
    assert stored.probability == 10
    assert stored.amount == Decimal("1000.50")
    assert created.version == 1
    assert audit_actions(session) == [DEAL_CREATED]
    assert [event.event_type for event in publisher.published] == [DEAL_CREATED]


async def test_a_stale_update_is_refused_before_anything_is_written() -> None:
    session = FakeSession()
    session.execute_queue = [[make_deal(version=2)]]

    with pytest.raises(VersionConflictError) as error:
        await make_service(session).update(
            OWN_ACCESS, DEAL_ID, UpdateDealRequest.model_validate({"version": 1, "title": "New"})
        )

    assert error.value.status_code == 409
    assert error.value.code == "DEAL_CONCURRENT_MODIFICATION"
    # Only the read happened: no write, and therefore no trail entry either.
    assert len(session.statements) == 1
    assert audit_actions(session) == []


async def test_an_update_is_guarded_by_the_version_stage_and_owner_it_read() -> None:
    session = FakeSession()
    session.execute_queue = [[make_deal()], [make_deal(probability=25, version=2)]]

    await make_service(session).update(
        OWN_ACCESS, DEAL_ID, UpdateDealRequest.model_validate({"version": 1, "probability": 25})
    )

    where_sql, where_params = where_of(session.statements[1])
    assert "deals.id = " in where_sql
    assert "deals.version = " in where_sql
    assert "deals.stage = " in where_sql
    assert "deals.deleted_at IS NULL" in where_sql
    assert "deals.owner_id = " in where_sql
    assert where_params["version_1"] == 1
    assert where_params["stage_1"] == DealStage.LEAD
    assert where_params["owner_id_1"] == ACTOR_ID


async def test_an_ordinary_update_never_writes_the_stage_column() -> None:
    session = FakeSession()
    session.execute_queue = [[make_deal()], [make_deal(title="Renamed", version=2)]]

    await make_service(session).update(
        OWN_ACCESS, DEAL_ID, UpdateDealRequest.model_validate({"version": 1, "title": "Renamed"})
    )

    set_clause, params = set_clause_of(session.statements[1])
    # The pipeline is advanced by one endpoint only; an edit that could set the
    # stage would make the whole machine decorative.
    assert "stage" not in set_clause
    assert "closed_at" not in set_clause
    assert params["title"] == "Renamed"
    # The counter moves in the database, not in Python, so two writers racing
    # on the same version cannot both land.
    assert "deals.version +" in set_clause


async def test_an_update_leaves_the_fields_the_client_did_not_send_alone() -> None:
    session = FakeSession()
    session.execute_queue = [[make_deal()], [make_deal(title="Renamed", version=2)]]

    await make_service(session).update(
        OWN_ACCESS, DEAL_ID, UpdateDealRequest.model_validate({"version": 1, "title": "Renamed"})
    )

    set_clause, _ = set_clause_of(session.statements[1])
    for untouched in ("currency", "amount", "probability", "contact_id", "expected_close_date"):
        assert untouched not in set_clause


async def test_an_explicit_null_clears_the_field_it_names() -> None:
    session = FakeSession()
    session.execute_queue = [[make_deal()], [make_deal(version=2)]]

    await make_service(session).update(
        OWN_ACCESS, DEAL_ID, UpdateDealRequest.model_validate({"version": 1, "contactId": None})
    )

    set_clause, params = set_clause_of(session.statements[1])
    assert "contact_id" in set_clause
    assert params["contact_id"] is None


async def test_a_move_the_pipeline_forbids_is_a_conflict() -> None:
    session = FakeSession()
    session.execute_queue = [[make_deal()]]

    with pytest.raises(ConflictError) as error:
        await make_service(session).transition(
            OWN_ACCESS,
            DEAL_ID,
            TransitionDealRequest.model_validate({"version": 1, "stage": "WON"}),
        )

    assert error.value.code == INVALID_DEAL_STAGE_TRANSITION
    assert len(session.statements) == 1
    assert audit_actions(session) == []


async def test_a_closed_deal_cannot_be_moved_anywhere() -> None:
    session = FakeSession()
    session.execute_queue = [[make_deal(stage=DealStage.WON, probability=100)]]

    with pytest.raises(ConflictError) as error:
        await make_service(session).transition(
            OWN_ACCESS,
            DEAL_ID,
            TransitionDealRequest.model_validate({"version": 1, "stage": "PROPOSAL"}),
        )

    assert error.value.code == INVALID_DEAL_STAGE_TRANSITION


async def test_closing_a_deal_stamps_the_moment_and_pins_the_probability() -> None:
    session = FakeSession()
    session.execute_queue = [
        [make_deal(stage=DealStage.PROPOSAL, probability=50)],
        [make_deal(stage=DealStage.WON, probability=100, version=2, closed_at=NOW)],
    ]
    publisher = RecordingPublisher()

    result = await make_service(session, publisher).transition(
        OWN_ACCESS, DEAL_ID, TransitionDealRequest.model_validate({"version": 1, "stage": "WON"})
    )

    set_clause, params = set_clause_of(session.statements[1])
    assert params["stage"] is DealStage.WON
    assert params["probability"] == 100
    assert params["closed_at"] is not None
    assert "closed_at" in set_clause
    assert result.stage is DealStage.WON
    assert audit_actions(session) == [DEAL_STAGE_TRANSITIONED]


async def test_an_open_stage_carries_no_closing_moment() -> None:
    session = FakeSession()
    session.execute_queue = [[make_deal()], [make_deal(stage=DealStage.QUALIFIED, version=2)]]

    await make_service(session).transition(
        OWN_ACCESS,
        DEAL_ID,
        TransitionDealRequest.model_validate({"version": 1, "stage": "QUALIFIED"}),
    )

    _, params = set_clause_of(session.statements[1])
    assert params["closed_at"] is None
    assert params["probability"] == 10


async def test_a_transition_lost_to_a_concurrent_writer_is_a_version_conflict() -> None:
    session = FakeSession()
    publisher = RecordingPublisher()
    # The read succeeds, the guarded write matches nothing: somebody else moved
    # the deal in between.
    session.execute_queue = [[make_deal()], []]

    with pytest.raises(VersionConflictError):
        await make_service(session, publisher).transition(
            OWN_ACCESS,
            DEAL_ID,
            TransitionDealRequest.model_validate({"version": 1, "stage": "QUALIFIED"}),
        )

    assert audit_actions(session) == []
    assert publisher.published == []


async def test_a_committed_transition_is_announced_with_both_stages() -> None:
    session = FakeSession()
    publisher = RecordingPublisher()
    session.execute_queue = [[make_deal()], [make_deal(stage=DealStage.QUALIFIED, version=2)]]

    await make_service(session, publisher).transition(
        OWN_ACCESS,
        DEAL_ID,
        TransitionDealRequest.model_validate({"version": 1, "stage": "QUALIFIED"}),
    )

    assert len(publisher.published) == 1
    event = publisher.published[0]
    assert event.event_type == DEAL_STAGE_TRANSITIONED
    assert event.entity_type == "deal"
    assert event.entity_id == str(DEAL_ID)
    assert event.payload["from"] == "LEAD"
    assert event.payload["to"] == "QUALIFIED"


async def test_a_broken_publisher_does_not_undo_a_written_transition() -> None:
    session = FakeSession()
    session.execute_queue = [[make_deal()], [make_deal(stage=DealStage.QUALIFIED, version=2)]]

    # The change is already written; a secondary consumer failing afterwards is
    # not the caller's problem.
    result = await make_service(session, BrokenPublisher()).transition(
        OWN_ACCESS,
        DEAL_ID,
        TransitionDealRequest.model_validate({"version": 1, "stage": "QUALIFIED"}),
    )

    assert result.stage is DealStage.QUALIFIED


async def test_a_narrow_grant_reads_somebody_elses_deal_as_missing() -> None:
    session = FakeSession()
    session.execute_queue = [[]]

    with pytest.raises(NotFoundError) as error:
        await make_service(session).get_by_id(OWN_ACCESS, DEAL_ID)

    assert error.value.status_code == 404
    assert error.value.code == DEAL_NOT_FOUND
    where_sql, where_params = where_of(session.statements[0])
    assert "deals.owner_id = " in where_sql
    assert where_params["owner_id_1"] == ACTOR_ID


async def test_a_narrow_grant_lists_only_its_own_deals() -> None:
    session = FakeSession()
    session.scalar_queue = [0]
    someone_else = uuid.uuid4()

    items, total = await make_service(session).list_deals(
        OWN_ACCESS, DealListParams.model_validate({"ownerId": str(someone_else)})
    )

    assert (items, total) == ([], 0)
    _, where_params = where_of(session.statements[0])
    # The requested owner is ignored rather than merged: a filter must never be
    # able to widen a grant.
    assert where_params["owner_id_1"] == ACTOR_ID
    assert someone_else not in where_params.values()


async def test_a_broad_grant_honours_the_requested_owner_filter() -> None:
    session = FakeSession()
    session.scalar_queue = [0]
    someone_else = uuid.uuid4()

    await make_service(session).list_deals(
        ALL_ACCESS, DealListParams.model_validate({"ownerId": str(someone_else)})
    )

    _, where_params = where_of(session.statements[0])
    assert where_params["owner_id_1"] == someone_else


async def test_deleting_stamps_the_row_instead_of_removing_it() -> None:
    session = FakeSession()
    publisher = RecordingPublisher()
    session.execute_queue = [[make_deal()], [DEAL_ID]]

    await make_service(session, publisher).delete(OWN_ACCESS, DEAL_ID, 1)

    set_clause, params = set_clause_of(session.statements[1])
    assert "deleted_at" in set_clause
    assert params["deleted_at"] is not None
    assert "deals.version +" in set_clause
    where_sql, where_params = where_of(session.statements[1])
    assert "deals.deleted_at IS NULL" in where_sql
    assert where_params["version_1"] == 1
    assert audit_actions(session) == [DEAL_DELETED]
    assert [event.event_type for event in publisher.published] == [DEAL_DELETED]


async def test_a_delete_lost_to_a_concurrent_writer_is_a_version_conflict() -> None:
    session = FakeSession()
    session.execute_queue = [[make_deal()], []]

    with pytest.raises(VersionConflictError):
        await make_service(session).delete(OWN_ACCESS, DEAL_ID, 1)

    assert audit_actions(session) == []


async def test_every_change_is_written_on_the_session_that_carries_it() -> None:
    session = FakeSession()
    session.execute_queue = [[make_deal()], [make_deal(title="Renamed", version=2)]]

    await make_service(session).update(
        OWN_ACCESS, DEAL_ID, UpdateDealRequest.model_validate({"version": 1, "title": "Renamed"})
    )

    entry = next(row for row in session.added if isinstance(row, AuditLog))
    assert entry.action == DEAL_UPDATED
    assert entry.entity_id == DEAL_ID
    assert entry.actor_id == ACTOR_ID
    assert entry.ip_address == "203.0.113.7"
    assert entry.changes is not None
    assert entry.changes["before"]["title"] == "Opportunity"
    assert entry.changes["after"]["title"] == "Renamed"
