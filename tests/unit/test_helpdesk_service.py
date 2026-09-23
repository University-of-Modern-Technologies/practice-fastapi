"""Ticket rules: the status machine, optimistic locking and the narrow grant.

The session is a scripted stand-in rather than a database, so what is asserted
here is the *statement* the service builds — which is where the version guard
and the ownership narrowing actually live.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    VersionConflictError,
)
from app.db.enums import (
    PermissionScope,
    TicketChannel,
    TicketPriority,
    TicketStatus,
)
from app.db.models.audit import AuditLog
from app.db.models.ticket import Ticket, TicketStatusLog
from app.events.types import DomainEvent
from app.modules.helpdesk.schemas import (
    CreateTicketRequest,
    TicketListParams,
    TransitionTicketRequest,
    UpdateTicketRequest,
)
from app.modules.helpdesk.service import (
    TICKET_NUMBER_ATTEMPTS,
    HelpdeskService,
    generate_ticket_number,
)
from app.modules.helpdesk.types import (
    TICKET_ASSIGNEE_NOT_FOUND,
    TICKET_CONCURRENT_MODIFICATION,
    TICKET_CONTACT_NOT_FOUND,
    TICKET_CREATED,
    TICKET_DELETED,
    TICKET_DUPLICATE_NUMBER,
    TICKET_NOT_FOUND,
    TICKET_STATUS_TRANSITIONED,
    TICKET_TRANSITION_NOT_ALLOWED,
    TICKET_UPDATED,
    TicketAccess,
)

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)
ACTOR_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
TICKET_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
OTHER_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")

OWN_ACCESS = TicketAccess(actor_id=ACTOR_ID, scope=PermissionScope.OWN, ip_address="203.0.113.7")
ALL_ACCESS = TicketAccess(actor_id=ACTOR_ID, scope=PermissionScope.ALL)

MINIMAL_CREATE: dict[str, Any] = {
    "subject": "Cannot sign in",
    "body": "The password reset link expires before it arrives.",
    "channel": "EMAIL",
}

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


class FakeSavepoint:
    """Stands in for the nested transaction the insert is retried inside."""

    async def __aenter__(self) -> FakeSavepoint:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class FakeSession:
    """A scripted stand-in: each call pops the next prepared answer."""

    def __init__(self, flush_error: Exception | None = None) -> None:
        self.execute_queue: list[list[Any]] = []
        self.scalar_queue: list[Any] = []
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.flushes = 0
        self.refreshed: list[Any] = []
        self.savepoints = 0
        self._flush_error = flush_error

    def begin_nested(self) -> FakeSavepoint:
        self.savepoints += 1
        return FakeSavepoint()

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
        if self._flush_error is not None:
            raise self._flush_error
        for row in self.added:
            if isinstance(row, Ticket) and getattr(row, "created_at", None) is None:
                row.created_at = NOW
                row.updated_at = NOW
                row.opened_at = NOW
            if isinstance(row, AuditLog) and getattr(row, "id", None) is None:
                row.id = uuid.uuid4()
                row.created_at = NOW

    async def refresh(self, instance: Any) -> None:
        self.refreshed.append(instance)


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.published.append(event)


class BrokenPublisher:
    def publish(self, _event: DomainEvent) -> None:
        message = "event stream unreachable"
        raise RuntimeError(message)


def make_ticket(**overrides: Any) -> Ticket:
    values: dict[str, Any] = {
        "id": TICKET_ID,
        "number": "TKT-00000042",
        "subject": "Cannot sign in",
        "body": "The password reset link expires before it arrives.",
        "channel": TicketChannel.EMAIL,
        "status": TicketStatus.NEW,
        "priority": TicketPriority.NORMAL,
        "owner_id": ACTOR_ID,
        "contact_id": None,
        "assignee_id": None,
        "version": 1,
        "opened_at": NOW,
        "resolved_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        "deleted_at": None,
    }
    return Ticket(**(values | overrides))


def make_service(session: FakeSession, publisher: Any = None) -> HelpdeskService:
    return HelpdeskService(cast("AsyncSession", session), publisher)


def audit_actions(session: FakeSession) -> list[str]:
    return [row.action for row in session.added if isinstance(row, AuditLog)]


def status_logs(session: FakeSession) -> list[TicketStatusLog]:
    return [row for row in session.added if isinstance(row, TicketStatusLog)]


def where_of(statement: Any) -> tuple[str, dict[str, Any]]:
    compiled = statement.whereclause.compile(dialect=PG_DIALECT)
    return str(compiled), dict(compiled.params)


def set_clause_of(statement: Any) -> tuple[str, dict[str, Any]]:
    compiled = statement.compile(dialect=PG_DIALECT)
    return str(compiled).split(" WHERE ")[0], dict(compiled.params)


# --- the number -----------------------------------------------------------


def test_a_ticket_number_has_the_published_shape() -> None:
    for _ in range(50):
        assert re.fullmatch(r"TKT-\d{8}", generate_ticket_number())


def test_two_numbers_drawn_in_a_row_are_not_a_sequence() -> None:
    # Guessable numbers would be a way to address other people's tickets; the
    # draw is random, so a run of identical values is what would be suspicious.
    drawn = {generate_ticket_number() for _ in range(50)}

    assert len(drawn) > 1


# --- creation -------------------------------------------------------------


async def test_a_new_ticket_starts_as_new_and_is_recorded() -> None:
    session = FakeSession()
    publisher = RecordingPublisher()
    data = CreateTicketRequest.model_validate(MINIMAL_CREATE)

    created = await make_service(session, publisher).create(OWN_ACCESS, data)

    stored = next(row for row in session.added if isinstance(row, Ticket))
    assert stored.status is TicketStatus.NEW
    assert stored.owner_id == ACTOR_ID
    assert stored.priority is TicketPriority.NORMAL
    assert stored.resolved_at is None
    assert re.fullmatch(r"TKT-\d{8}", stored.number)
    assert created.version == 1
    assert audit_actions(session) == [TICKET_CREATED]
    assert [event.event_type for event in publisher.published] == [TICKET_CREATED]


async def test_creating_a_ticket_opens_its_status_log() -> None:
    session = FakeSession()

    await make_service(session).create(
        OWN_ACCESS, CreateTicketRequest.model_validate(MINIMAL_CREATE)
    )

    logs = status_logs(session)
    assert len(logs) == 1
    # The opening entry is the only one with no previous status: it records a
    # ticket appearing rather than moving.
    assert logs[0].from_status is None
    assert logs[0].to_status is TicketStatus.NEW
    assert logs[0].changed_by_id == ACTOR_ID


async def test_a_narrow_grant_cannot_file_a_ticket_for_somebody_else() -> None:
    session = FakeSession()
    data = CreateTicketRequest.model_validate(MINIMAL_CREATE | {"ownerId": str(OTHER_ID)})

    with pytest.raises(ForbiddenError) as error:
        await make_service(session).create(OWN_ACCESS, data)

    # Forbidden rather than missing: the caller is naming a user, not
    # addressing a ticket, so there is no identifier to keep secret.
    assert error.value.status_code == 403
    assert session.added == []


async def test_a_wide_grant_may_file_a_ticket_for_somebody_else() -> None:
    session = FakeSession()
    data = CreateTicketRequest.model_validate(MINIMAL_CREATE | {"ownerId": str(OTHER_ID)})

    created = await make_service(session).create(ALL_ACCESS, data)

    assert created.owner_id == OTHER_ID


async def test_a_contact_the_caller_cannot_see_is_refused() -> None:
    session = FakeSession()
    session.scalar_queue = [None]
    data = CreateTicketRequest.model_validate(MINIMAL_CREATE | {"contactId": str(uuid.uuid4())})

    with pytest.raises(NotFoundError) as error:
        await make_service(session).create(OWN_ACCESS, data)

    assert error.value.status_code == 404
    assert error.value.code == TICKET_CONTACT_NOT_FOUND
    assert session.added == []


async def test_the_contact_lookup_is_narrowed_by_the_callers_grant() -> None:
    session = FakeSession()
    session.scalar_queue = [None]
    data = CreateTicketRequest.model_validate(MINIMAL_CREATE | {"contactId": str(uuid.uuid4())})

    with pytest.raises(NotFoundError):
        await make_service(session).create(OWN_ACCESS, data)

    where_sql, where_params = where_of(session.statements[0])
    assert "contacts.owner_id = " in where_sql
    assert where_params["owner_id_1"] == ACTOR_ID


async def test_an_assignee_that_is_not_an_active_account_is_refused() -> None:
    session = FakeSession()
    session.scalar_queue = [None]
    data = CreateTicketRequest.model_validate(MINIMAL_CREATE | {"assigneeId": str(OTHER_ID)})

    with pytest.raises(NotFoundError) as error:
        await make_service(session).create(OWN_ACCESS, data)

    assert error.value.status_code == 404
    assert error.value.code == TICKET_ASSIGNEE_NOT_FOUND
    where_sql, _ = where_of(session.statements[0])
    assert "users.is_active IS true" in where_sql


async def test_a_number_that_keeps_colliding_is_reported_by_name() -> None:
    taken = IntegrityError("INSERT INTO tickets", {}, Exception("tickets_number_key"))
    session = FakeSession(taken)

    with pytest.raises(ConflictError) as error:
        await make_service(session).create(
            OWN_ACCESS, CreateTicketRequest.model_validate(MINIMAL_CREATE)
        )

    # The unique index settles the draw; a caller unlucky every time is told
    # rather than handed one more attempt behind their back.
    assert error.value.status_code == 409
    assert error.value.code == TICKET_DUPLICATE_NUMBER
    assert error.value.message == "Could not allocate a ticket number"
    assert session.savepoints == TICKET_NUMBER_ATTEMPTS
    assert audit_actions(session) == []


async def test_a_collision_is_redrawn_rather_than_reported() -> None:
    session = FakeSession()
    session.execute_queue = []

    await make_service(session).create(
        OWN_ACCESS, CreateTicketRequest.model_validate(MINIMAL_CREATE)
    )

    # The insert goes through a savepoint even when it succeeds: a failed
    # statement would otherwise leave the surrounding transaction unusable.
    assert session.savepoints == 1


async def test_an_integrity_failure_that_is_not_the_number_is_not_retried() -> None:
    broken = IntegrityError("INSERT INTO tickets", {}, Exception("tickets_owner_id_fkey"))
    session = FakeSession(broken)

    with pytest.raises(IntegrityError):
        await make_service(session).create(
            OWN_ACCESS, CreateTicketRequest.model_validate(MINIMAL_CREATE)
        )

    assert session.savepoints == 1


# --- editing --------------------------------------------------------------


async def test_a_stale_update_is_refused_before_anything_is_written() -> None:
    session = FakeSession()
    session.execute_queue = [[make_ticket(version=2)]]

    with pytest.raises(VersionConflictError) as error:
        await make_service(session).update(
            OWN_ACCESS,
            TICKET_ID,
            UpdateTicketRequest.model_validate({"version": 1, "subject": "New"}),
        )

    assert error.value.status_code == 409
    assert error.value.code == TICKET_CONCURRENT_MODIFICATION
    assert error.value.message == "Ticket was modified by another request"
    # Only the read happened: no write, and therefore no trail entry either.
    assert len(session.statements) == 1
    assert audit_actions(session) == []


async def test_an_update_is_guarded_by_the_version_status_and_owner_it_read() -> None:
    session = FakeSession()
    session.execute_queue = [[make_ticket()], [make_ticket(subject="Renamed", version=2)]]

    await make_service(session).update(
        OWN_ACCESS,
        TICKET_ID,
        UpdateTicketRequest.model_validate({"version": 1, "subject": "Renamed"}),
    )

    where_sql, where_params = where_of(session.statements[1])
    assert "tickets.id = " in where_sql
    assert "tickets.version = " in where_sql
    assert "tickets.status = " in where_sql
    assert "tickets.deleted_at IS NULL" in where_sql
    assert "tickets.owner_id = " in where_sql
    assert where_params["version_1"] == 1
    assert where_params["status_1"] == TicketStatus.NEW
    assert where_params["owner_id_1"] == ACTOR_ID


async def test_an_ordinary_update_never_writes_the_status_column() -> None:
    session = FakeSession()
    session.execute_queue = [[make_ticket()], [make_ticket(subject="Renamed", version=2)]]

    await make_service(session).update(
        OWN_ACCESS,
        TICKET_ID,
        UpdateTicketRequest.model_validate({"version": 1, "subject": "Renamed"}),
    )

    set_clause, params = set_clause_of(session.statements[1])
    # The lifecycle is advanced by one endpoint only; an edit that could set the
    # status would make the whole machine decorative.
    assert "status" not in set_clause
    assert "resolved_at" not in set_clause
    assert params["subject"] == "Renamed"
    # The counter moves in the database, not in Python, so two writers racing
    # on the same version cannot both land.
    assert "tickets.version +" in set_clause
    assert audit_actions(session) == [TICKET_UPDATED]


async def test_an_update_leaves_the_fields_the_client_did_not_send_alone() -> None:
    session = FakeSession()
    session.execute_queue = [[make_ticket()], [make_ticket(subject="Renamed", version=2)]]

    await make_service(session).update(
        OWN_ACCESS,
        TICKET_ID,
        UpdateTicketRequest.model_validate({"version": 1, "subject": "Renamed"}),
    )

    set_clause, _ = set_clause_of(session.statements[1])
    for untouched in ("body", "channel", "priority", "contact_id", "assignee_id"):
        assert untouched not in set_clause


async def test_an_explicit_null_clears_the_field_it_names() -> None:
    session = FakeSession()
    session.execute_queue = [[make_ticket()], [make_ticket(version=2)]]

    await make_service(session).update(
        OWN_ACCESS,
        TICKET_ID,
        UpdateTicketRequest.model_validate({"version": 1, "assigneeId": None}),
    )

    set_clause, params = set_clause_of(session.statements[1])
    assert "assignee_id" in set_clause
    assert params["assignee_id"] is None


async def test_an_update_lost_to_a_concurrent_writer_is_a_version_conflict() -> None:
    session = FakeSession()
    publisher = RecordingPublisher()
    # The read succeeds, the guarded write matches nothing: somebody else moved
    # the ticket in between.
    session.execute_queue = [[make_ticket()], []]

    with pytest.raises(VersionConflictError):
        await make_service(session, publisher).update(
            OWN_ACCESS,
            TICKET_ID,
            UpdateTicketRequest.model_validate({"version": 1, "subject": "Renamed"}),
        )

    assert audit_actions(session) == []
    assert publisher.published == []


# --- the lifecycle --------------------------------------------------------


async def test_a_move_the_lifecycle_forbids_is_unprocessable() -> None:
    session = FakeSession()
    session.execute_queue = [[make_ticket()]]

    with pytest.raises(AppError) as error:
        await make_service(session).transition(
            OWN_ACCESS,
            TICKET_ID,
            TransitionTicketRequest.model_validate({"toStatus": "RESOLVED", "version": 1}),
        )

    assert error.value.status_code == 422
    assert error.value.code == TICKET_TRANSITION_NOT_ALLOWED
    assert len(session.statements) == 1
    assert audit_actions(session) == []
    assert status_logs(session) == []


async def test_a_closed_ticket_cannot_be_moved_anywhere() -> None:
    session = FakeSession()
    session.execute_queue = [[make_ticket(status=TicketStatus.CLOSED, resolved_at=NOW)]]

    with pytest.raises(AppError) as error:
        await make_service(session).transition(
            OWN_ACCESS,
            TICKET_ID,
            TransitionTicketRequest.model_validate({"toStatus": "OPEN", "version": 1}),
        )

    assert error.value.code == TICKET_TRANSITION_NOT_ALLOWED


async def test_resolving_a_ticket_stamps_the_moment() -> None:
    session = FakeSession()
    session.execute_queue = [
        [make_ticket(status=TicketStatus.OPEN)],
        [make_ticket(status=TicketStatus.RESOLVED, version=2, resolved_at=NOW)],
    ]

    result = await make_service(session).transition(
        OWN_ACCESS,
        TICKET_ID,
        TransitionTicketRequest.model_validate({"toStatus": "RESOLVED", "version": 1}),
    )

    set_clause, params = set_clause_of(session.statements[1])
    assert "resolved_at" in set_clause
    assert params["status"] is TicketStatus.RESOLVED
    assert params["resolved_at"] is not None
    assert result.status is TicketStatus.RESOLVED
    assert audit_actions(session) == [TICKET_STATUS_TRANSITIONED]


async def test_reopening_a_resolved_ticket_clears_the_moment() -> None:
    session = FakeSession()
    session.execute_queue = [
        [make_ticket(status=TicketStatus.RESOLVED, resolved_at=NOW)],
        [make_ticket(status=TicketStatus.OPEN, version=2)],
    ]

    await make_service(session).transition(
        OWN_ACCESS,
        TICKET_ID,
        TransitionTicketRequest.model_validate({"toStatus": "OPEN", "version": 1}),
    )

    set_clause, params = set_clause_of(session.statements[1])
    # A stale resolution moment on a reopened ticket would misreport how long
    # the customer waited.
    assert "resolved_at" in set_clause
    assert params["resolved_at"] is None


async def test_closing_a_resolved_ticket_keeps_the_moment_it_was_resolved() -> None:
    session = FakeSession()
    session.execute_queue = [
        [make_ticket(status=TicketStatus.RESOLVED, resolved_at=NOW)],
        [make_ticket(status=TicketStatus.CLOSED, version=2, resolved_at=NOW)],
    ]

    result = await make_service(session).transition(
        OWN_ACCESS,
        TICKET_ID,
        TransitionTicketRequest.model_validate({"toStatus": "CLOSED", "version": 1}),
    )

    set_clause, _ = set_clause_of(session.statements[1])
    # The column is not in the statement at all: closing decides nothing about
    # whether the ticket was answered, so it writes nothing about it. Without
    # this the time-to-resolution report would lose exactly the records that
    # reached the end.
    assert "resolved_at" not in set_clause
    assert result.resolved_at == NOW


async def test_closing_an_unanswered_ticket_leaves_it_without_a_resolution() -> None:
    session = FakeSession()
    session.execute_queue = [
        [make_ticket()],
        [make_ticket(status=TicketStatus.CLOSED, version=2)],
    ]

    result = await make_service(session).transition(
        OWN_ACCESS,
        TICKET_ID,
        TransitionTicketRequest.model_validate({"toStatus": "CLOSED", "version": 1}),
    )

    # Spam, a duplicate, a customer who vanished: closed without ever being
    # answered is a normal ending, not a gap to be filled in.
    set_clause, _ = set_clause_of(session.statements[1])
    assert "resolved_at" not in set_clause
    assert result.resolved_at is None


async def test_a_transition_appends_to_the_status_log_with_its_note() -> None:
    session = FakeSession()
    session.execute_queue = [[make_ticket()], [make_ticket(status=TicketStatus.OPEN, version=2)]]

    await make_service(session).transition(
        OWN_ACCESS,
        TICKET_ID,
        TransitionTicketRequest.model_validate(
            {"toStatus": "OPEN", "version": 1, "note": "picked up"}
        ),
    )

    logs = status_logs(session)
    assert len(logs) == 1
    assert logs[0].ticket_id == TICKET_ID
    assert logs[0].from_status is TicketStatus.NEW
    assert logs[0].to_status is TicketStatus.OPEN
    assert logs[0].note == "picked up"
    assert logs[0].changed_by_id == ACTOR_ID


async def test_a_transition_lost_to_a_concurrent_writer_leaves_no_trace() -> None:
    session = FakeSession()
    publisher = RecordingPublisher()
    session.execute_queue = [[make_ticket()], []]

    with pytest.raises(VersionConflictError):
        await make_service(session, publisher).transition(
            OWN_ACCESS,
            TICKET_ID,
            TransitionTicketRequest.model_validate({"toStatus": "OPEN", "version": 1}),
        )

    assert audit_actions(session) == []
    assert status_logs(session) == []
    assert publisher.published == []


async def test_a_committed_transition_is_announced_with_both_statuses() -> None:
    session = FakeSession()
    publisher = RecordingPublisher()
    session.execute_queue = [[make_ticket()], [make_ticket(status=TicketStatus.OPEN, version=2)]]

    await make_service(session, publisher).transition(
        OWN_ACCESS,
        TICKET_ID,
        TransitionTicketRequest.model_validate({"toStatus": "OPEN", "version": 1}),
    )

    assert len(publisher.published) == 1
    event = publisher.published[0]
    assert event.event_type == TICKET_STATUS_TRANSITIONED
    assert event.entity_type == "ticket"
    assert event.entity_id == str(TICKET_ID)
    assert event.payload["from"] == "NEW"
    assert event.payload["to"] == "OPEN"


async def test_a_broken_publisher_does_not_undo_a_written_transition() -> None:
    session = FakeSession()
    session.execute_queue = [[make_ticket()], [make_ticket(status=TicketStatus.OPEN, version=2)]]

    # The change is already written; a secondary consumer failing afterwards is
    # not the caller's problem.
    result = await make_service(session, BrokenPublisher()).transition(
        OWN_ACCESS,
        TICKET_ID,
        TransitionTicketRequest.model_validate({"toStatus": "OPEN", "version": 1}),
    )

    assert result.status is TicketStatus.OPEN


# --- removal --------------------------------------------------------------


async def test_a_deleted_ticket_is_stamped_rather_than_dropped() -> None:
    session = FakeSession()
    publisher = RecordingPublisher()
    session.execute_queue = [[make_ticket()], [TICKET_ID]]

    await make_service(session, publisher).delete(OWN_ACCESS, TICKET_ID, 1)

    set_clause, params = set_clause_of(session.statements[1])
    assert "deleted_at" in set_clause
    assert params["deleted_at"] is not None
    assert audit_actions(session) == [TICKET_DELETED]
    assert [event.event_type for event in publisher.published] == [TICKET_DELETED]


async def test_a_stale_delete_is_refused() -> None:
    session = FakeSession()
    session.execute_queue = [[make_ticket(version=3)]]

    with pytest.raises(VersionConflictError) as error:
        await make_service(session).delete(OWN_ACCESS, TICKET_ID, 1)

    assert error.value.code == TICKET_CONCURRENT_MODIFICATION
    assert audit_actions(session) == []


async def test_a_delete_lost_to_a_concurrent_writer_is_a_version_conflict() -> None:
    session = FakeSession()
    session.execute_queue = [[make_ticket()], []]

    with pytest.raises(VersionConflictError):
        await make_service(session).delete(OWN_ACCESS, TICKET_ID, 1)

    assert audit_actions(session) == []


# --- the narrow grant -----------------------------------------------------


async def test_a_narrow_grant_reads_somebody_elses_ticket_as_missing() -> None:
    session = FakeSession()
    session.execute_queue = [[]]

    with pytest.raises(NotFoundError) as error:
        await make_service(session).get_by_id(OWN_ACCESS, TICKET_ID)

    assert error.value.status_code == 404
    assert error.value.code == TICKET_NOT_FOUND
    where_sql, where_params = where_of(session.statements[0])
    assert "tickets.owner_id = " in where_sql
    assert where_params["owner_id_1"] == ACTOR_ID


async def test_a_narrow_grant_lists_only_its_own_tickets() -> None:
    session = FakeSession()
    session.scalar_queue = [0]
    params = TicketListParams.model_validate({"ownerId": str(OTHER_ID)})

    items, total = await make_service(session).list_tickets(OWN_ACCESS, params)

    assert items == []
    assert total == 0
    # The scope narrows the query itself, and the client's own `ownerId` is
    # ignored rather than merged: it could otherwise widen the result set.
    where_sql, where_params = where_of(session.statements[0])
    assert "tickets.owner_id = " in where_sql
    assert where_params["owner_id_1"] == ACTOR_ID
    assert OTHER_ID not in where_params.values()


async def test_a_wide_grant_may_filter_by_whichever_owner_was_asked_for() -> None:
    session = FakeSession()
    session.scalar_queue = [0]
    params = TicketListParams.model_validate({"ownerId": str(OTHER_ID)})

    await make_service(session).list_tickets(ALL_ACCESS, params)

    _, where_params = where_of(session.statements[0])
    assert where_params["owner_id_1"] == OTHER_ID


async def test_a_listing_never_shows_a_deleted_ticket() -> None:
    session = FakeSession()
    session.scalar_queue = [0]

    await make_service(session).list_tickets(ALL_ACCESS, TicketListParams.model_validate({}))

    where_sql, _ = where_of(session.statements[0])
    assert "tickets.deleted_at IS NULL" in where_sql


async def test_the_page_is_ordered_with_the_id_as_a_tiebreaker() -> None:
    session = FakeSession()
    session.scalar_queue = [0]
    params = TicketListParams.model_validate({"sortBy": "priority", "sortOrder": "asc"})

    await make_service(session).list_tickets(ALL_ACCESS, params)

    order_by = str(session.statements[1].compile(dialect=PG_DIALECT))
    assert "ORDER BY tickets.priority ASC, tickets.id ASC" in order_by


async def test_the_published_filters_reach_the_where_clause() -> None:
    session = FakeSession()
    session.scalar_queue = [0]
    contact_id = uuid.uuid4()
    params = TicketListParams.model_validate(
        {
            "status": "OPEN",
            "channel": "CHAT",
            "priority": "URGENT",
            "contactId": str(contact_id),
            "assigneeId": str(OTHER_ID),
            "openedFrom": "2026-08-01T00:00:00Z",
            "openedTo": "2026-08-31T00:00:00Z",
            "search": "sign in",
        }
    )

    await make_service(session).list_tickets(ALL_ACCESS, params)

    where_sql, where_params = where_of(session.statements[0])
    assert "tickets.status = " in where_sql
    assert "tickets.channel = " in where_sql
    assert "tickets.priority = " in where_sql
    assert "tickets.contact_id = " in where_sql
    assert "tickets.assignee_id = " in where_sql
    assert "tickets.opened_at >= " in where_sql
    assert "tickets.opened_at <= " in where_sql
    assert "tickets.subject ILIKE " in where_sql
    assert "tickets.number ILIKE " in where_sql
    assert where_params["contact_id_1"] == contact_id


async def test_a_search_term_cannot_smuggle_a_wildcard_through() -> None:
    session = FakeSession()
    session.scalar_queue = [0]

    await make_service(session).list_tickets(
        ALL_ACCESS, TicketListParams.model_validate({"search": "100%"})
    )

    _, where_params = where_of(session.statements[0])
    # Left unescaped, `%` would match every row rather than the literal sign.
    assert where_params["subject_1"] == "%100\\%%"
