"""Call rules: idempotent import, optimistic locking and the narrow grant.

The session is a scripted stand-in rather than a database, so what is asserted
here is the *statement* the service builds — which is where the version guard
and the ownership narrowing actually live.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.db.enums import CallDirection, CallDisposition, PermissionScope
from app.db.models.audit import AuditLog
from app.db.models.call import Call
from app.events.types import DomainEvent
from app.modules.calls.provider import (
    CallProviderFetchRequest,
    ProviderCall,
    call_provider_unavailable_error,
)
from app.modules.calls.schemas import CallListParams, LinkCallRequest, UpdateCallRequest
from app.modules.calls.service import RECORDING_URL_TTL_SECONDS, CallsService
from app.modules.calls.stub_provider import (
    STUB_CALL_JOURNAL_SIZE,
    StubCallProvider,
    stub_journal,
)
from app.modules.calls.types import (
    CALL_CONCURRENT_MODIFICATION,
    CALL_CONTACT_NOT_FOUND,
    CALL_CREATED,
    CALL_DEAL_NOT_FOUND,
    CALL_DELETED,
    CALL_LINKED,
    CALL_NOT_FOUND,
    CALL_PROVIDER_UNAVAILABLE,
    CALL_RECORDING_UNAVAILABLE,
    CALL_UPDATED,
    CallAccess,
)

NOW = datetime(2026, 9, 1, 8, 0, 0, 123_000, tzinfo=UTC)
ACTOR_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
CALL_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
OTHER_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
CONTACT_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
DEAL_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")

OWN_ACCESS = CallAccess(actor_id=ACTOR_ID, scope=PermissionScope.OWN, ip_address="203.0.113.7")
ALL_ACCESS = CallAccess(actor_id=ACTOR_ID, scope=PermissionScope.ALL)

#: Statements are compiled against the dialect the application actually runs on,
#: so what is asserted is the SQL the database would receive.
PG_DIALECT = cast("Any", postgresql).dialect()


class FakeScalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return list(self._values)

    def unique(self) -> FakeScalars:
        return self

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
    """Stands in for the nested transaction each insert is filed inside."""

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
        #: Failures keyed by the identifier of the row they fire on, so one
        #: insert in a batch can lose its race while its neighbours do not.
        self.flush_errors: dict[str, Exception] = {}
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
        for row in list(self.added):
            if isinstance(row, Call) and getattr(row, "created_at", None) is None:
                error = self._flush_error or self.flush_errors.pop(row.external_id, None)
                if error is not None:
                    # A savepoint rollback discards the row it was holding.
                    self.added.remove(row)
                    raise error
                row.created_at = NOW
                row.updated_at = NOW
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


class StaticProvider:
    """Hands back a fixed batch, or fails the way a real one would."""

    name = "static"

    def __init__(
        self, batch: list[ProviderCall] | None = None, failure: Exception | None = None
    ) -> None:
        self._batch = batch if batch is not None else []
        self._failure = failure
        self.requests: list[CallProviderFetchRequest] = []

    async def fetch_calls(self, request: CallProviderFetchRequest) -> list[ProviderCall]:
        self.requests.append(request)
        if self._failure is not None:
            raise self._failure
        return self._batch


def make_call(**overrides: Any) -> Call:
    values: dict[str, Any] = {
        "id": CALL_ID,
        "external_id": "stub-call-0000",
        "direction": CallDirection.INBOUND,
        "disposition": CallDisposition.ANSWERED,
        "from_number": "+380671230001",
        "to_number": "+380442001010",
        "started_at": NOW,
        "duration_seconds": 61,
        "owner_id": ACTOR_ID,
        "contact_id": None,
        "deal_id": None,
        "recording_url": None,
        "notes": None,
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
        "deleted_at": None,
    }
    return Call(**(values | overrides))


def make_service(session: FakeSession, provider: Any = None, publisher: Any = None) -> CallsService:
    return CallsService(
        cast("AsyncSession", session),
        provider if provider is not None else StubCallProvider(),
        publisher,
    )


def audit_actions(session: FakeSession) -> list[str]:
    return [row.action for row in session.added if isinstance(row, AuditLog)]


def stored_calls(session: FakeSession) -> list[Call]:
    return [row for row in session.added if isinstance(row, Call)]


def sql_of(statement: Any) -> tuple[str, dict[str, Any]]:
    compiled = statement.compile(dialect=PG_DIALECT)
    return str(compiled), dict(compiled.params)


def where_of(statement: Any) -> tuple[str, dict[str, Any]]:
    compiled = statement.whereclause.compile(dialect=PG_DIALECT)
    return str(compiled), dict(compiled.params)


def set_clause_of(statement: Any) -> str:
    compiled = statement.compile(dialect=PG_DIALECT)
    return str(compiled).split(" WHERE ")[0]


# --- the import, and the promise it makes ---------------------------------


async def test_a_first_sync_files_the_whole_batch() -> None:
    session = FakeSession()
    publisher = RecordingPublisher()

    result = await make_service(session, publisher=publisher).sync(ALL_ACCESS)

    assert result.fetched == STUB_CALL_JOURNAL_SIZE
    assert result.created == STUB_CALL_JOURNAL_SIZE
    assert result.skipped == 0
    assert len(stored_calls(session)) == STUB_CALL_JOURNAL_SIZE
    assert audit_actions(session) == [CALL_CREATED] * STUB_CALL_JOURNAL_SIZE
    announced = [event.event_type for event in publisher.published]
    assert announced == [CALL_CREATED] * STUB_CALL_JOURNAL_SIZE


async def test_the_same_batch_arriving_twice_creates_nothing_the_second_time() -> None:
    """The guarantee the module exists for, stated as a test.

    The first sync files everything; the second is given a table that already
    holds those identifiers and must file none of them.
    """
    first_session = FakeSession()
    first = await make_service(first_session).sync(ALL_ACCESS)

    already_on_file = [call.external_id for call in stored_calls(first_session)]
    second_session = FakeSession()
    second_session.execute_queue = [already_on_file]
    publisher = RecordingPublisher()

    second = await make_service(second_session, publisher=publisher).sync(ALL_ACCESS)

    assert first.created == STUB_CALL_JOURNAL_SIZE
    assert second.fetched == STUB_CALL_JOURNAL_SIZE
    assert second.created == 0
    assert second.skipped == STUB_CALL_JOURNAL_SIZE
    assert stored_calls(second_session) == []
    assert audit_actions(second_session) == []
    assert publisher.published == []


async def test_a_batch_that_repeats_a_call_files_it_once() -> None:
    # A provider listing the same call twice is repeating itself, not reporting
    # a collision.
    duplicated = [stub_journal()[0], stub_journal()[0], stub_journal()[1]]
    session = FakeSession()

    result = await make_service(session, StaticProvider(duplicated)).sync(ALL_ACCESS)

    assert result.fetched == 3
    assert result.created == 2
    assert result.skipped == 1


async def test_a_partly_known_batch_files_only_what_is_new() -> None:
    batch = list(stub_journal()[:4])
    session = FakeSession()
    session.execute_queue = [[batch[0].external_id, batch[2].external_id]]

    result = await make_service(session, StaticProvider(batch)).sync(ALL_ACCESS)

    assert (result.fetched, result.created, result.skipped) == (4, 2, 2)
    assert [call.external_id for call in stored_calls(session)] == [
        batch[1].external_id,
        batch[3].external_id,
    ]


async def test_the_existence_check_deliberately_ignores_the_soft_delete_flag() -> None:
    # A call somebody deleted on purpose must not come back because the
    # provider mentioned it again.
    session = FakeSession()

    await make_service(session, StaticProvider([stub_journal()[0]])).sync(ALL_ACCESS)

    lookup_sql, _ = sql_of(session.statements[0])
    assert "calls.external_id IN" in lookup_sql
    assert "deleted_at" not in lookup_sql


async def test_the_batch_is_looked_up_in_one_query() -> None:
    # A sync that issues a lookup per row turns a routine import into a few
    # hundred round trips.
    session = FakeSession()

    await make_service(session).sync(ALL_ACCESS)

    assert len(session.statements) == 1


async def test_an_imported_call_belongs_to_nobody() -> None:
    # The provider knows telephone numbers, not which colleague the
    # conversation belongs to.
    session = FakeSession()

    await make_service(session).sync(ALL_ACCESS)

    for call in stored_calls(session):
        assert call.owner_id is None
        assert call.contact_id is None
        assert call.deal_id is None
        assert call.version == 1


async def test_a_batch_with_nothing_new_is_not_flushed_at_all() -> None:
    session = FakeSession()
    session.execute_queue = [[call.external_id for call in stub_journal()]]

    await make_service(session).sync(ALL_ACCESS)

    assert session.flushes == 0


async def test_a_collision_at_the_database_is_a_skip_rather_than_a_failure() -> None:
    """A duplicate external id is the ordinary outcome, not a refusal.

    The lookup races with a concurrent sync, and the loser of that race has
    already got what it wanted: the call is on file. So the whole import
    succeeds and simply reports nothing created.
    """
    collision = IntegrityError("INSERT", {}, Exception("duplicate key value: calls_external_id"))
    session = FakeSession(flush_error=collision)

    result = await make_service(session).sync(ALL_ACCESS)

    assert result.fetched == STUB_CALL_JOURNAL_SIZE
    assert result.created == 0
    assert result.skipped == STUB_CALL_JOURNAL_SIZE
    assert audit_actions(session) == []


async def test_one_lost_race_does_not_cost_the_rest_of_the_batch() -> None:
    """Why each row goes in its own savepoint.

    In PostgreSQL a unique violation poisons the whole transaction. Batched,
    one call a colleague imported a second earlier would take the entire
    import down with it.
    """
    batch = list(stub_journal()[:3])
    session = FakeSession()
    session.flush_errors = {
        batch[1].external_id: IntegrityError(
            "INSERT", {}, Exception("duplicate key value: calls_external_id")
        )
    }

    result = await make_service(session, StaticProvider(batch)).sync(ALL_ACCESS)

    assert (result.fetched, result.created, result.skipped) == (3, 2, 1)
    assert session.savepoints == 3
    assert [call.external_id for call in stored_calls(session)] == [
        batch[0].external_id,
        batch[2].external_id,
    ]


async def test_an_integrity_violation_that_is_not_a_duplicate_is_not_swallowed() -> None:
    # Anything but the unique external id belongs elsewhere — a foreign key
    # that vanished, a check that failed — and hiding it as a skip would report
    # a successful import of rows that were never written.
    other = IntegrityError("INSERT", {}, Exception("violates check constraint duration"))
    session = FakeSession(flush_error=other)

    with pytest.raises(IntegrityError):
        await make_service(session).sync(ALL_ACCESS)


async def test_an_unreachable_provider_is_reported_as_a_bad_gateway() -> None:
    session = FakeSession()
    provider = StaticProvider(failure=call_provider_unavailable_error())

    with pytest.raises(AppError) as error:
        await make_service(session, provider).sync(ALL_ACCESS)

    assert error.value.status_code == 502
    assert error.value.code == CALL_PROVIDER_UNAVAILABLE
    # Nothing was written, and no event claims otherwise.
    assert session.added == []
    assert session.flushes == 0


async def test_an_unreachable_provider_does_not_disturb_the_other_endpoints() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call()]]
    provider = StaticProvider(failure=call_provider_unavailable_error())

    found = await make_service(session, provider).get_by_id(ALL_ACCESS, CALL_ID)

    assert found.id == CALL_ID


# --- browsing -------------------------------------------------------------


async def test_a_narrow_grant_never_selects_somebody_elses_call() -> None:
    session = FakeSession()

    await make_service(session).list_calls(OWN_ACCESS, CallListParams())

    page_sql, params = sql_of(session.statements[1])
    assert "calls.owner_id = " in page_sql
    assert ACTOR_ID in params.values()


async def test_a_narrow_grant_cannot_widen_the_page_with_an_owner_filter() -> None:
    session = FakeSession()

    await make_service(session).list_calls(OWN_ACCESS, CallListParams(owner_id=OTHER_ID))

    _, params = sql_of(session.statements[1])
    assert OTHER_ID not in params.values()


async def test_an_unowned_call_falls_outside_a_narrow_grant() -> None:
    """The decision this module had to make, asserted as SQL.

    ``owner_id = :actor`` is never true of a NULL, so a call nobody has claimed
    is invisible to a narrow grant — without a special case, and identically on
    any engine.
    """
    session = FakeSession()

    await make_service(session).list_calls(OWN_ACCESS, CallListParams())

    page_sql, _ = sql_of(session.statements[1])
    assert "calls.owner_id = " in page_sql
    assert "calls.owner_id IS NULL" not in page_sql


async def test_a_wide_grant_sees_the_whole_log() -> None:
    session = FakeSession()

    await make_service(session).list_calls(ALL_ACCESS, CallListParams())

    where_sql, _ = where_of(session.statements[1])
    assert "calls.owner_id" not in where_sql


async def test_the_page_is_ordered_by_when_people_spoke_and_tie_broken_by_id() -> None:
    session = FakeSession()

    await make_service(session).list_calls(ALL_ACCESS, CallListParams())

    ordering = sql_of(session.statements[1])[0].split(" ORDER BY ")[1]
    assert ordering.startswith("calls.started_at DESC")
    assert "calls.id ASC" in ordering


@pytest.mark.parametrize(
    ("has_contact", "expected"),
    [(True, "calls.contact_id IS NOT NULL"), (False, "calls.contact_id IS NULL")],
)
async def test_the_absence_filter_asks_about_absence(has_contact: bool, expected: str) -> None:
    session = FakeSession()

    await make_service(session).list_calls(ALL_ACCESS, CallListParams(has_contact=has_contact))

    assert expected in sql_of(session.statements[1])[0]


async def test_a_deleted_call_is_gone_for_readers() -> None:
    session = FakeSession()

    await make_service(session).list_calls(ALL_ACCESS, CallListParams())

    assert "calls.deleted_at IS NULL" in sql_of(session.statements[1])[0]


async def test_somebody_elses_call_is_reported_as_missing_rather_than_forbidden() -> None:
    # A 403 would confirm the id exists, which turns the endpoint into an
    # enumeration oracle.
    session = FakeSession()

    with pytest.raises(NotFoundError) as error:
        await make_service(session).get_by_id(OWN_ACCESS, CALL_ID)

    assert error.value.status_code == 404
    assert error.value.code == CALL_NOT_FOUND


# --- editing --------------------------------------------------------------


async def test_an_edit_writes_only_the_fields_the_client_named() -> None:
    session = FakeSession()
    existing = make_call()
    session.execute_queue = [[existing], [make_call(notes="Call-back agreed", version=2)]]

    updated = await make_service(session).update(
        ALL_ACCESS, CALL_ID, UpdateCallRequest.model_validate({"version": 1, "notes": "  x  "})
    )

    written = set_clause_of(session.statements[1])
    assert "notes" in written
    assert "direction" not in written
    assert "duration_seconds" not in written
    assert updated.version == 2
    assert audit_actions(session) == [CALL_UPDATED]


async def test_the_version_the_caller_read_guards_the_write() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call(version=3)], [make_call(version=4)]]

    await make_service(session).update(
        ALL_ACCESS, CALL_ID, UpdateCallRequest.model_validate({"version": 3, "notes": "x"})
    )

    write_sql, params = sql_of(session.statements[1])
    # The guard lives in the statement, not in a Python comparison that a
    # concurrent writer could slip past.
    assert "calls.version = " in write_sql
    assert 3 in params.values()


async def test_a_stale_version_is_refused_under_the_modules_own_code() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call(version=5)]]

    with pytest.raises(ConflictError) as error:
        await make_service(session).update(
            ALL_ACCESS, CALL_ID, UpdateCallRequest.model_validate({"version": 1, "notes": "x"})
        )

    assert error.value.status_code == 409
    assert error.value.code == CALL_CONCURRENT_MODIFICATION


async def test_a_version_that_moved_between_the_read_and_the_write_is_refused() -> None:
    session = FakeSession()
    # The read succeeds, the guarded write matches nothing: somebody else won.
    session.execute_queue = [[make_call(version=1)], []]

    with pytest.raises(ConflictError) as error:
        await make_service(session).update(
            ALL_ACCESS, CALL_ID, UpdateCallRequest.model_validate({"version": 1, "notes": "x"})
        )

    assert error.value.code == CALL_CONCURRENT_MODIFICATION


async def test_a_contact_the_caller_cannot_see_is_refused() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call()]]
    session.scalar_queue = [None]

    with pytest.raises(NotFoundError) as error:
        await make_service(session).update(
            OWN_ACCESS,
            CALL_ID,
            UpdateCallRequest.model_validate({"version": 1, "contactId": str(CONTACT_ID)}),
        )

    assert error.value.code == CALL_CONTACT_NOT_FOUND


async def test_the_contact_lookup_is_narrowed_by_the_callers_grant() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call()]]
    session.scalar_queue = [None]

    with pytest.raises(NotFoundError):
        await make_service(session).update(
            OWN_ACCESS,
            CALL_ID,
            UpdateCallRequest.model_validate({"version": 1, "contactId": str(CONTACT_ID)}),
        )

    where_sql, params = where_of(session.statements[1])
    assert "contacts.owner_id = " in where_sql
    assert ACTOR_ID in params.values()


async def test_a_deal_the_caller_cannot_see_is_refused() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call()]]
    session.scalar_queue = [None]

    with pytest.raises(NotFoundError) as error:
        await make_service(session).update(
            OWN_ACCESS,
            CALL_ID,
            UpdateCallRequest.model_validate({"version": 1, "dealId": str(DEAL_ID)}),
        )

    assert error.value.code == CALL_DEAL_NOT_FOUND


async def test_clearing_an_association_costs_no_lookup() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call(contact_id=CONTACT_ID)], [make_call(version=2)]]

    await make_service(session).update(
        ALL_ACCESS, CALL_ID, UpdateCallRequest.model_validate({"version": 1, "contactId": None})
    )

    # Read, then write. Detaching asks nothing of the contacts table.
    assert len(session.statements) == 2
    write_sql, _ = sql_of(session.statements[1])
    assert "contact_id" in write_sql


async def test_a_narrow_grant_cannot_hand_a_call_to_a_colleague() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call()]]

    with pytest.raises(ForbiddenError) as error:
        await make_service(session).update(
            OWN_ACCESS,
            CALL_ID,
            UpdateCallRequest.model_validate({"version": 1, "ownerId": str(OTHER_ID)}),
        )

    # Forbidden rather than missing: the caller is naming a user, not
    # addressing a call, so there is no identifier to keep secret.
    assert error.value.status_code == 403


async def test_a_narrow_grant_cannot_release_a_call_back_to_nobody() -> None:
    # Releasing it puts the call beyond the caller's own view, which is giving
    # it away by another name.
    session = FakeSession()
    session.execute_queue = [[make_call()]]

    with pytest.raises(ForbiddenError):
        await make_service(session).update(
            OWN_ACCESS, CALL_ID, UpdateCallRequest.model_validate({"version": 1, "ownerId": None})
        )


async def test_a_wide_grant_may_both_assign_and_release() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call()], [make_call(owner_id=None, version=2)]]

    released = await make_service(session).update(
        ALL_ACCESS, CALL_ID, UpdateCallRequest.model_validate({"version": 1, "ownerId": None})
    )

    assert released.owner_id is None


# --- linking --------------------------------------------------------------


async def test_linking_is_recorded_as_its_own_act() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call()], [make_call(contact_id=CONTACT_ID, version=2)]]
    session.scalar_queue = [CONTACT_ID]
    publisher = RecordingPublisher()

    request = LinkCallRequest.model_validate({"version": 1, "contactId": str(CONTACT_ID)})
    linked = await make_service(session, publisher=publisher).link(ALL_ACCESS, CALL_ID, request)

    assert linked.contact_id == CONTACT_ID
    assert audit_actions(session) == [CALL_LINKED]
    assert [event.event_type for event in publisher.published] == [CALL_LINKED]


async def test_linking_is_guarded_by_the_version_too() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call(version=2)]]
    session.scalar_queue = [DEAL_ID]
    request = LinkCallRequest.model_validate({"version": 1, "dealId": str(DEAL_ID)})

    with pytest.raises(ConflictError) as error:
        await make_service(session).link(ALL_ACCESS, CALL_ID, request)

    assert error.value.code == CALL_CONCURRENT_MODIFICATION


# --- listening back -------------------------------------------------------


async def test_a_recording_link_expires() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call(recording_url="https://recordings.invalid/a.mp3")]]

    before = datetime.now(tz=UTC)
    recording = await make_service(session).get_recording(ALL_ACCESS, CALL_ID)

    assert recording.url == "https://recordings.invalid/a.mp3"
    assert (recording.expires_at - before).total_seconds() <= RECORDING_URL_TTL_SECONDS + 5
    assert recording.expires_at > before


async def test_a_call_with_no_audio_is_reported_under_its_own_code() -> None:
    # A call nobody answered has nothing to listen to: an ordinary outcome, and
    # one a client has to be able to tell from "no such call".
    session = FakeSession()
    session.execute_queue = [[make_call(recording_url=None)]]

    with pytest.raises(NotFoundError) as error:
        await make_service(session).get_recording(ALL_ACCESS, CALL_ID)

    assert error.value.status_code == 404
    assert error.value.code == CALL_RECORDING_UNAVAILABLE


async def test_listening_back_asks_nothing_of_the_provider() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call(recording_url="https://recordings.invalid/a.mp3")]]
    provider = StaticProvider(failure=call_provider_unavailable_error())

    recording = await make_service(session, provider).get_recording(ALL_ACCESS, CALL_ID)

    assert recording.url


# --- removal --------------------------------------------------------------


async def test_a_deleted_call_keeps_its_row() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call()], [CALL_ID]]
    publisher = RecordingPublisher()

    await make_service(session, publisher=publisher).delete(ALL_ACCESS, CALL_ID, 1)

    written = set_clause_of(session.statements[1])
    assert written.startswith("UPDATE calls SET")
    assert "deleted_at=" in written
    assert audit_actions(session) == [CALL_DELETED]
    assert [event.event_type for event in publisher.published] == [CALL_DELETED]


async def test_deleting_with_a_stale_version_is_refused() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call(version=2)]]

    with pytest.raises(ConflictError) as error:
        await make_service(session).delete(ALL_ACCESS, CALL_ID, 1)

    assert error.value.code == CALL_CONCURRENT_MODIFICATION


async def test_deleting_is_narrowed_by_the_callers_grant() -> None:
    session = FakeSession()
    session.execute_queue = [[make_call()], [CALL_ID]]

    await make_service(session).delete(OWN_ACCESS, CALL_ID, 1)

    write_sql, params = sql_of(session.statements[1])
    assert "calls.owner_id = " in write_sql
    assert ACTOR_ID in params.values()
