"""Finance rules: an idempotent import, the reconciliation rule, and locking.

The session is a scripted stand-in rather than a database, so what is asserted
here is the *statement* the service builds — which is where the version guard
and the paired match columns actually live — together with what it decided to
write, record and announce.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.enums import OrderStatus, PaymentMatchStatus, PermissionScope, TransactionDirection
from app.db.models.audit import AuditLog
from app.db.models.finance import BankStatement, BankTransaction
from app.db.models.order import Order
from app.events.types import DomainEvent
from app.modules.finance.provider import ProviderStatement
from app.modules.finance.schemas import (
    FinanceSummaryParams,
    MatchTransactionRequest,
    TransactionListParams,
)
from app.modules.finance.service import RECONCILE_BATCH_SIZE, FinanceService
from app.modules.finance.stub_provider import STUB_TRANSACTION_COUNT, stub_statement
from app.modules.finance.types import (
    BANK_PROVIDER_UNAVAILABLE,
    STATEMENT_DUPLICATE_EXTERNAL_ID,
    STATEMENT_ENTITY_TYPE,
    STATEMENT_IMPORTED,
    STATEMENT_NOT_FOUND,
    TRANSACTION_ALREADY_MATCHED,
    TRANSACTION_AMOUNT_MISMATCH,
    TRANSACTION_CONCURRENT_MODIFICATION,
    TRANSACTION_ENTITY_TYPE,
    TRANSACTION_MATCHED,
    TRANSACTION_NOT_FOUND,
    TRANSACTION_NOT_MATCHED,
    TRANSACTION_ORDER_NOT_FOUND,
    TRANSACTION_UNMATCHED,
    FinanceAccess,
)

NOW = datetime(2026, 1, 1, 8, 0, 0, 123_000, tzinfo=UTC)
BOOKED_AT = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
ORDER_PLACED_AT = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

ACTOR_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
TRANSACTION_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
STATEMENT_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
ORDER_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
OTHER_ORDER_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")
CONTACT_ID = uuid.UUID("66666666-6666-4666-8666-666666666666")

ACCESS = FinanceAccess(actor_id=ACTOR_ID, scope=PermissionScope.ALL, ip_address="203.0.113.7")

#: Statements are compiled against the dialect the application actually runs
#: on, so what is asserted is the SQL the database would receive.
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

    def all(self) -> list[Any]:
        return list(self._values)

    def first(self) -> Any:
        return self._values[0] if self._values else None


class FakeSavepoint:
    """Stands in for the nested transaction each insert is filed inside."""

    async def __aenter__(self) -> FakeSavepoint:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class FakeSession:
    """A scripted stand-in: each call pops the next prepared answer."""

    def __init__(self) -> None:
        self.execute_queue: list[list[Any]] = []
        self.scalar_queue: list[Any] = []
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.flushes = 0
        self.savepoints = 0
        self.refreshed: list[Any] = []
        #: Failures keyed by the identifier of the row they fire on, so one
        #: insert in a batch can lose its race while its neighbours do not.
        self.flush_errors: dict[str, Exception] = {}

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
            if isinstance(row, BankStatement | BankTransaction):
                if getattr(row, "created_at", None) is not None:
                    continue
                error = self.flush_errors.pop(row.external_id, None)
                if error is not None:
                    # A savepoint rollback discards the row it was holding.
                    self.added.remove(row)
                    raise error
                row.created_at = NOW
                row.updated_at = NOW
                if isinstance(row, BankStatement):
                    row.imported_at = NOW
            if isinstance(row, AuditLog) and getattr(row, "id", None) is None:
                row.id = uuid.uuid4()
                row.created_at = NOW

    async def refresh(self, instance: Any) -> None:
        """A real refresh re-reads server defaults the flush above already set."""
        self.refreshed.append(instance)


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.published.append(event)


class StaticProvider:
    """Hands back a fixed statement, or fails the way a real one would."""

    name = "static"

    def __init__(
        self, statement: ProviderStatement | None = None, failure: Exception | None = None
    ) -> None:
        self._statement = statement if statement is not None else stub_statement()
        self._failure = failure
        self.calls = 0

    async def fetch_statement(self) -> ProviderStatement:
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        return self._statement


def integrity_error(message: str) -> IntegrityError:
    return IntegrityError("INSERT", {}, Exception(message))


def make_transaction(**overrides: Any) -> BankTransaction:
    values: dict[str, Any] = {
        "id": TRANSACTION_ID,
        "statement_id": STATEMENT_ID,
        "external_id": "stub-txn-0001",
        "booked_at": BOOKED_AT,
        "amount": Decimal("1800.00"),
        "currency": "USD",
        "direction": TransactionDirection.CREDIT,
        "counterparty_name": "Alex North",
        "counterparty_account": None,
        "reference": "Payment for ORD-2026-0001",
        "match_status": PaymentMatchStatus.UNMATCHED,
        "matched_order_id": None,
        "matched_at": None,
        "matched_by_id": None,
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return BankTransaction(**(values | overrides))


def candidate_row(
    order_id: uuid.UUID = ORDER_ID,
    order_number: str = "ORD-2026-0001",
    total: str = "1800.00",
    status: OrderStatus = OrderStatus.CONFIRMED,
) -> tuple[Any, ...]:
    """One row of the candidate query, in the order the service selects it."""
    return (
        order_id,
        order_number,
        status,
        Decimal(total),
        "USD",
        CONTACT_ID,
        ORDER_PLACED_AT,
        "Alex",
        "North",
        None,
    )


def make_order(total: str = "1800.00", **overrides: Any) -> Order:
    values: dict[str, Any] = {
        "id": ORDER_ID,
        "order_number": "ORD-2026-0001",
        "owner_id": ACTOR_ID,
        "status": OrderStatus.CONFIRMED,
        "currency": "USD",
        "subtotal": Decimal(total),
        "discount_total": Decimal("0.00"),
        "tax_total": Decimal("0.00"),
        "total": Decimal(total),
        "version": 1,
        "placed_at": ORDER_PLACED_AT,
        "created_at": ORDER_PLACED_AT,
        "updated_at": ORDER_PLACED_AT,
    }
    return Order(**(values | overrides))


def make_service(
    session: FakeSession, provider: Any = None, publisher: Any = None
) -> FinanceService:
    return FinanceService(
        cast("AsyncSession", session),
        provider if provider is not None else StaticProvider(),
        publisher,
    )


def audit_actions(session: FakeSession) -> list[str]:
    return [row.action for row in session.added if isinstance(row, AuditLog)]


def stored_transactions(session: FakeSession) -> list[BankTransaction]:
    return [row for row in session.added if isinstance(row, BankTransaction)]


def sql_of(statement: Any) -> str:
    return str(statement.compile(dialect=PG_DIALECT))


def where_of(statement: Any) -> str:
    return str(statement.whereclause.compile(dialect=PG_DIALECT))


def set_clause_of(statement: Any) -> str:
    return sql_of(statement).split(" WHERE ")[0]


def queue_for_import(session: FakeSession, known: list[str] | None = None) -> None:
    """The two reads every import performs before it writes anything."""
    session.execute_queue = [[], known or []]


# --- the import, and the promise it makes ----------------------------------


async def test_a_first_import_files_the_whole_statement() -> None:
    session = FakeSession()
    publisher = RecordingPublisher()
    queue_for_import(session)

    result = await make_service(session, publisher=publisher).import_statement(ACCESS)

    assert result.imported == STUB_TRANSACTION_COUNT
    assert result.skipped == 0
    assert len(stored_transactions(session)) == STUB_TRANSACTION_COUNT
    assert audit_actions(session) == [STATEMENT_IMPORTED]
    announced = publisher.published[0]
    assert announced.event_type == STATEMENT_IMPORTED
    # An import is an event about the statement, not about any one of its lines.
    assert announced.entity_type == STATEMENT_ENTITY_TYPE


async def test_the_same_statement_arriving_twice_files_nothing_the_second_time() -> None:
    """The guarantee the import exists for, stated as a test."""
    first_session = FakeSession()
    queue_for_import(first_session)
    first = await make_service(first_session).import_statement(ACCESS)

    already_on_file = [row.external_id for row in stored_transactions(first_session)]
    second_session = FakeSession()
    statement = BankStatement(
        id=STATEMENT_ID,
        external_id=stub_statement().external_id,
        account_label="Operating account",
        period_start=stub_statement().period_start,
        period_end=stub_statement().period_end,
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("11025.49"),
        currency="USD",
        imported_by_id=ACTOR_ID,
        imported_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    second_session.execute_queue = [[statement], already_on_file]
    publisher = RecordingPublisher()

    second = await make_service(second_session, publisher=publisher).import_statement(ACCESS)

    assert first.imported == STUB_TRANSACTION_COUNT
    assert second.imported == 0
    assert second.skipped == STUB_TRANSACTION_COUNT
    assert second.statement_id == STATEMENT_ID
    assert stored_transactions(second_session) == []
    # Nothing changed, so nothing is announced: an import that found the ledger
    # already complete is not an event anybody needs to hear about.
    assert audit_actions(second_session) == []
    assert publisher.published == []


async def test_a_feed_that_repeats_a_line_files_it_once() -> None:
    feed = stub_statement()
    repeated = ProviderStatement(
        external_id=feed.external_id,
        account_label=feed.account_label,
        period_start=feed.period_start,
        period_end=feed.period_end,
        currency=feed.currency,
        opening_balance=feed.opening_balance,
        closing_balance=feed.closing_balance,
        transactions=(feed.transactions[0], feed.transactions[0], feed.transactions[1]),
    )
    session = FakeSession()
    queue_for_import(session)

    result = await make_service(session, StaticProvider(repeated)).import_statement(ACCESS)

    assert result.imported == 2
    assert result.skipped == 1


async def test_a_partly_known_statement_files_only_what_is_new() -> None:
    session = FakeSession()
    queue_for_import(session, known=["stub-txn-2026-01-0001", "stub-txn-2026-01-0003"])

    result = await make_service(session).import_statement(ACCESS)

    assert result.imported == STUB_TRANSACTION_COUNT - 2
    assert result.skipped == 2
    filed = [row.external_id for row in stored_transactions(session)]
    assert "stub-txn-2026-01-0001" not in filed
    assert "stub-txn-2026-01-0003" not in filed


async def test_the_batch_is_looked_up_in_one_query() -> None:
    # An import that issues a lookup per row turns a routine pull into a few
    # hundred round trips.
    session = FakeSession()
    queue_for_import(session)

    await make_service(session).import_statement(ACCESS)

    lookups = [sql_of(item) for item in session.statements]
    assert sum("bank_transactions.external_id IN" in sql for sql in lookups) == 1


async def test_a_line_that_lost_its_race_is_counted_as_skipped() -> None:
    """A collision during an import is the ordinary case, not a failure.

    In PostgreSQL a unique violation poisons the whole transaction, so each
    insert goes in its own savepoint: the loser rolls back alone and its
    neighbours survive.
    """
    session = FakeSession()
    queue_for_import(session)
    session.flush_errors["stub-txn-2026-01-0002"] = integrity_error(
        'duplicate key value violates unique constraint "bank_transactions_external_id_key"'
    )

    result = await make_service(session).import_statement(ACCESS)

    assert result.imported == STUB_TRANSACTION_COUNT - 1
    assert result.skipped == 1
    assert session.savepoints == STUB_TRANSACTION_COUNT + 1


async def test_an_integrity_failure_that_is_not_a_duplicate_is_raised() -> None:
    # A foreign key that vanished is a fault, and counting it as "skipped"
    # would make an import report success while losing a line.
    session = FakeSession()
    queue_for_import(session)
    session.flush_errors["stub-txn-2026-01-0001"] = integrity_error(
        'violates foreign key constraint "bank_transactions_statement_id_fkey"'
    )

    with pytest.raises(IntegrityError):
        await make_service(session).import_statement(ACCESS)


async def test_a_statement_that_lost_its_race_is_reported() -> None:
    """Reported rather than absorbed: the retry is a no-op anyway."""
    session = FakeSession()
    session.execute_queue = [[]]
    session.flush_errors["stub-stmt-2026-01"] = integrity_error(
        'duplicate key value violates unique constraint "bank_statements_external_id_key"'
    )

    with pytest.raises(ConflictError) as failure:
        await make_service(session).import_statement(ACCESS)

    assert failure.value.code == STATEMENT_DUPLICATE_EXTERNAL_ID
    assert failure.value.status_code == 409


async def test_an_imported_line_claims_nothing_about_what_it_paid_for() -> None:
    # The bank knows what arrived, not what it was for. An import that also
    # guessed would leave no way to tell the two apart afterwards.
    session = FakeSession()
    queue_for_import(session)

    await make_service(session).import_statement(ACCESS)

    for row in stored_transactions(session):
        assert row.match_status is PaymentMatchStatus.UNMATCHED
        assert row.matched_order_id is None
        assert row.matched_at is None
        assert row.matched_by_id is None
        assert row.version == 1


async def test_the_statement_records_who_imported_it() -> None:
    session = FakeSession()
    queue_for_import(session)

    await make_service(session).import_statement(ACCESS)

    statement = next(row for row in session.added if isinstance(row, BankStatement))
    assert statement.imported_by_id == ACTOR_ID
    assert statement.opening_balance == Decimal("10000.00")


async def test_an_unreachable_bank_is_reported_as_a_bad_gateway() -> None:
    """Never a 500: the caller learns the feed is down, and nothing else."""
    session = FakeSession()
    provider = StaticProvider(failure=TimeoutError("connection timed out"))

    with pytest.raises(AppError) as failure:
        await make_service(session, provider).import_statement(ACCESS)

    assert failure.value.code == BANK_PROVIDER_UNAVAILABLE
    assert failure.value.status_code == 502
    # Nothing about the upstream leaks into the message the caller reads.
    assert "timed out" not in failure.value.message


async def test_a_failed_import_writes_nothing_at_all() -> None:
    session = FakeSession()
    provider = StaticProvider(failure=TimeoutError("connection timed out"))

    with pytest.raises(AppError):
        await make_service(session, provider).import_statement(ACCESS)

    assert session.added == []
    assert session.statements == []


# --- matching by hand ------------------------------------------------------


async def test_a_manual_match_sets_the_four_columns_together() -> None:
    """The check constraint pairs them, and so does every write here."""
    session = FakeSession()
    matched = make_transaction(
        match_status=PaymentMatchStatus.MATCHED,
        matched_order_id=ORDER_ID,
        matched_at=NOW,
        matched_by_id=ACTOR_ID,
        version=2,
    )
    session.execute_queue = [[make_transaction()], [make_order()], [matched]]
    publisher = RecordingPublisher()

    result = await make_service(session, publisher=publisher).match(
        ACCESS, TRANSACTION_ID, MatchTransactionRequest(order_id=ORDER_ID, version=1)
    )

    assert result.match_status is PaymentMatchStatus.MATCHED
    assert result.matched_order_id == ORDER_ID
    assignments = set_clause_of(session.statements[2])
    assert "match_status" in assignments
    assert "matched_order_id" in assignments
    assert "matched_at" in assignments
    assert "matched_by_id" in assignments
    # And the version moves in the same statement, so nothing can observe the
    # row half-updated.
    assert "bank_transactions.version + " in assignments


async def test_a_manual_match_is_guarded_by_the_version_in_the_statement() -> None:
    # Re-checking in Python would leave a window in which another request could
    # slip a match in between the read and the write.
    session = FakeSession()
    session.execute_queue = [[make_transaction()], [make_order()], [make_transaction(version=2)]]

    await make_service(session).match(
        ACCESS, TRANSACTION_ID, MatchTransactionRequest(order_id=ORDER_ID, version=1)
    )

    guard = where_of(session.statements[2])
    assert "bank_transactions.id" in guard
    assert "bank_transactions.version" in guard


async def test_a_manual_match_is_recorded_and_announced() -> None:
    session = FakeSession()
    session.execute_queue = [[make_transaction()], [make_order()], [make_transaction(version=2)]]
    publisher = RecordingPublisher()

    await make_service(session, publisher=publisher).match(
        ACCESS, TRANSACTION_ID, MatchTransactionRequest(order_id=ORDER_ID, version=1)
    )

    assert audit_actions(session) == [TRANSACTION_MATCHED]
    entry = next(row for row in session.added if isinstance(row, AuditLog))
    assert entry.entity_type == TRANSACTION_ENTITY_TYPE
    assert entry.ip_address == "203.0.113.7"
    assert set(entry.changes or {}) == {"before", "after"}
    announced = publisher.published[0]
    assert announced.event_type == TRANSACTION_MATCHED
    assert announced.entity_type == TRANSACTION_ENTITY_TYPE


async def test_matching_an_amount_a_cent_out_is_allowed() -> None:
    """The tolerance is the same one the automatic rule uses."""
    session = FakeSession()
    session.execute_queue = [
        [make_transaction(amount=Decimal("1799.99"))],
        [make_order()],
        [make_transaction(version=2)],
    ]

    result = await make_service(session).match(
        ACCESS, TRANSACTION_ID, MatchTransactionRequest(order_id=ORDER_ID, version=1)
    )

    assert result.version == 2


async def test_matching_an_amount_that_cannot_settle_the_order_is_refused() -> None:
    session = FakeSession()
    session.execute_queue = [[make_transaction(amount=Decimal("10.00"))], [make_order()]]

    with pytest.raises(ConflictError) as failure:
        await make_service(session).match(
            ACCESS, TRANSACTION_ID, MatchTransactionRequest(order_id=ORDER_ID, version=1)
        )

    assert failure.value.code == TRANSACTION_AMOUNT_MISMATCH


async def test_matching_an_order_nobody_can_see_is_reported_with_our_own_code() -> None:
    # A code naming the orders module would send the client to re-read the
    # wrong resource.
    session = FakeSession()
    session.execute_queue = [[make_transaction()], []]

    with pytest.raises(NotFoundError) as failure:
        await make_service(session).match(
            ACCESS, TRANSACTION_ID, MatchTransactionRequest(order_id=ORDER_ID, version=1)
        )

    assert failure.value.code == TRANSACTION_ORDER_NOT_FOUND


async def test_matching_something_already_matched_is_refused() -> None:
    session = FakeSession()
    session.execute_queue = [
        [make_transaction(match_status=PaymentMatchStatus.MATCHED, matched_order_id=OTHER_ORDER_ID)]
    ]

    with pytest.raises(ConflictError) as failure:
        await make_service(session).match(
            ACCESS, TRANSACTION_ID, MatchTransactionRequest(order_id=ORDER_ID, version=1)
        )

    assert failure.value.code == TRANSACTION_ALREADY_MATCHED
    assert failure.value.status_code == 409


async def test_a_stale_version_loses_the_race_before_anything_is_read() -> None:
    session = FakeSession()
    session.execute_queue = [[make_transaction(version=4)]]

    with pytest.raises(ConflictError) as failure:
        await make_service(session).match(
            ACCESS, TRANSACTION_ID, MatchTransactionRequest(order_id=ORDER_ID, version=1)
        )

    assert failure.value.code == TRANSACTION_CONCURRENT_MODIFICATION
    # The wording is part of the contract, not a detail of this backend.
    assert failure.value.message == "Transaction was modified by another request"


async def test_a_write_that_finds_the_row_moved_on_reports_the_conflict() -> None:
    # The guarded update returns nothing when somebody else got there first.
    session = FakeSession()
    session.execute_queue = [[make_transaction()], [make_order()], []]

    with pytest.raises(ConflictError) as failure:
        await make_service(session).match(
            ACCESS, TRANSACTION_ID, MatchTransactionRequest(order_id=ORDER_ID, version=1)
        )

    assert failure.value.code == TRANSACTION_CONCURRENT_MODIFICATION


async def test_matching_a_transaction_that_does_not_exist_is_a_not_found() -> None:
    session = FakeSession()

    with pytest.raises(NotFoundError) as failure:
        await make_service(session).match(
            ACCESS, TRANSACTION_ID, MatchTransactionRequest(order_id=ORDER_ID, version=1)
        )

    assert failure.value.code == TRANSACTION_NOT_FOUND


# --- taking a match back ---------------------------------------------------


async def test_unmatching_clears_the_four_columns_together() -> None:
    session = FakeSession()
    matched = make_transaction(
        match_status=PaymentMatchStatus.MATCHED,
        matched_order_id=ORDER_ID,
        matched_at=NOW,
        matched_by_id=ACTOR_ID,
        version=2,
    )
    session.execute_queue = [[matched], [make_transaction(version=3)]]
    publisher = RecordingPublisher()

    result = await make_service(session, publisher=publisher).unmatch(ACCESS, TRANSACTION_ID, 2)

    assert result.match_status is PaymentMatchStatus.UNMATCHED
    assert result.matched_order_id is None
    assert audit_actions(session) == [TRANSACTION_UNMATCHED]
    assert [event.event_type for event in publisher.published] == [TRANSACTION_UNMATCHED]


async def test_unmatching_returns_the_payment_to_the_queue_rather_than_to_a_guess() -> None:
    # Restoring a stale SUGGESTED would put a week-old guess back in front of
    # the next person to look at it.
    session = FakeSession()
    matched = make_transaction(
        match_status=PaymentMatchStatus.MATCHED, matched_order_id=ORDER_ID, version=2
    )
    session.execute_queue = [[matched], [make_transaction(version=3)]]

    await make_service(session).unmatch(ACCESS, TRANSACTION_ID, 2)

    assignments = set_clause_of(session.statements[1])
    assert "match_status" in assignments


async def test_unmatching_something_that_was_never_matched_is_refused() -> None:
    session = FakeSession()
    session.execute_queue = [[make_transaction(match_status=PaymentMatchStatus.SUGGESTED)]]

    with pytest.raises(ConflictError) as failure:
        await make_service(session).unmatch(ACCESS, TRANSACTION_ID, 1)

    assert failure.value.code == TRANSACTION_NOT_MATCHED


async def test_unmatching_with_a_stale_version_is_refused() -> None:
    session = FakeSession()
    session.execute_queue = [[make_transaction(match_status=PaymentMatchStatus.MATCHED, version=5)]]

    with pytest.raises(ConflictError) as failure:
        await make_service(session).unmatch(ACCESS, TRANSACTION_ID, 1)

    assert failure.value.code == TRANSACTION_CONCURRENT_MODIFICATION


# --- reading one transaction -----------------------------------------------


async def test_a_suggested_transaction_is_published_with_its_candidates() -> None:
    session = FakeSession()
    session.execute_queue = [
        [make_transaction(match_status=PaymentMatchStatus.SUGGESTED)],
        [candidate_row(), candidate_row(order_id=OTHER_ORDER_ID, order_number="ORD-2026-0009")],
    ]

    result = await make_service(session).get_transaction(ACCESS, TRANSACTION_ID)

    assert [item.order_id for item in result.candidates] == [ORDER_ID, OTHER_ORDER_ID]
    assert result.candidates[0].total == Decimal("1800.00")


async def test_a_settled_transaction_carries_no_candidates() -> None:
    # A matched line has an answer and an unmatched one had none to offer;
    # neither is a question, so neither costs a query.
    session = FakeSession()
    session.execute_queue = [[make_transaction(match_status=PaymentMatchStatus.UNMATCHED)]]

    result = await make_service(session).get_transaction(ACCESS, TRANSACTION_ID)

    assert result.candidates == []
    assert len(session.statements) == 1


async def test_reading_a_transaction_that_does_not_exist_is_a_not_found() -> None:
    session = FakeSession()

    with pytest.raises(NotFoundError) as failure:
        await make_service(session).get_transaction(ACCESS, TRANSACTION_ID)

    assert failure.value.code == TRANSACTION_NOT_FOUND


# --- browsing the ledger ---------------------------------------------------


async def test_a_filter_naming_a_statement_that_does_not_exist_is_reported() -> None:
    """Rather than answered with an empty page, which would look like an answer."""
    session = FakeSession()

    with pytest.raises(NotFoundError) as failure:
        await make_service(session).list_transactions(
            ACCESS, TransactionListParams(statement_id=STATEMENT_ID)
        )

    assert failure.value.code == STATEMENT_NOT_FOUND


async def test_an_amount_filter_reaches_the_query_as_an_exact_decimal() -> None:
    session = FakeSession()
    session.scalar_queue = [0]

    await make_service(session).list_transactions(
        ACCESS, TransactionListParams(min_amount="19.99", max_amount="1800.00")
    )

    page_statement = session.statements[-1]
    params = page_statement.compile(dialect=PG_DIALECT).params
    assert Decimal("19.99") in params.values()
    assert Decimal("1800.00") in params.values()


async def test_the_page_is_ordered_by_booking_with_the_id_as_the_tiebreaker() -> None:
    session = FakeSession()
    session.scalar_queue = [0]

    await make_service(session).list_transactions(ACCESS, TransactionListParams())

    ordering = sql_of(session.statements[-1]).split("ORDER BY")[1]
    assert "booked_at DESC" in ordering
    assert "bank_transactions.id ASC" in ordering


# --- the batch run ---------------------------------------------------------


async def test_reconcile_takes_in_every_line_that_is_still_open() -> None:
    # Both directions: outgoing money is examined too, and filed as IGNORED.
    session = FakeSession()

    await make_service(session).reconcile(ACCESS)

    criteria = where_of(session.statements[0])
    assert "bank_transactions.direction" not in criteria
    assert "bank_transactions.match_status IN" in criteria
    assert "LIMIT" in sql_of(session.statements[0])
    assert RECONCILE_BATCH_SIZE in session.statements[0].compile(dialect=PG_DIALECT).params.values()


async def test_one_fitting_order_settles_the_payment() -> None:
    session = FakeSession()
    matched = make_transaction(
        match_status=PaymentMatchStatus.MATCHED, matched_order_id=ORDER_ID, version=2
    )
    session.execute_queue = [[make_transaction()], [candidate_row()], [matched]]
    publisher = RecordingPublisher()

    result = await make_service(session, publisher=publisher).reconcile(ACCESS)

    assert (result.examined, result.matched, result.suggested, result.unmatched) == (1, 1, 0, 0)
    assert audit_actions(session) == [TRANSACTION_MATCHED]
    assert [event.event_type for event in publisher.published] == [TRANSACTION_MATCHED]


async def test_two_fitting_orders_become_a_question_rather_than_an_answer() -> None:
    session = FakeSession()
    suggested = make_transaction(match_status=PaymentMatchStatus.SUGGESTED, version=2)
    session.execute_queue = [
        [make_transaction(reference="Bank transfer", counterparty_name="Alex North")],
        [candidate_row(), candidate_row(order_id=OTHER_ORDER_ID, order_number="ORD-2026-0009")],
        [suggested],
    ]
    publisher = RecordingPublisher()

    result = await make_service(session, publisher=publisher).reconcile(ACCESS)

    assert (result.matched, result.suggested) == (0, 1)
    # Nothing was decided, so nothing is announced: a stream that reported every
    # re-run of the rule would drown the two announcements that matter.
    assert audit_actions(session) == []
    assert publisher.published == []


async def test_a_payment_that_fits_nothing_is_left_alone() -> None:
    session = FakeSession()
    session.execute_queue = [
        [make_transaction(reference="Incoming transfer", counterparty_name="Halcyon Supplies")],
        [],
    ]

    result = await make_service(session).reconcile(ACCESS)

    assert (result.examined, result.unmatched) == (1, 1)
    # Already UNMATCHED, so there is nothing to write either.
    assert len(session.statements) == 2


async def test_money_going_out_is_filed_rather_than_reconciled() -> None:
    # A payment we made is not settling an order somebody placed with us, but
    # it is still examined, and IGNORED is the answer rather than silence.
    session = FakeSession()
    session.execute_queue = [
        [make_transaction(direction=TransactionDirection.DEBIT)],
        [make_transaction(direction=TransactionDirection.DEBIT, version=2)],
    ]

    result = await make_service(session).reconcile(ACCESS)

    assert (result.examined, result.ignored, result.unmatched) == (1, 1, 0)
    # The order book is never consulted for it.
    assert "orders" not in sql_of(session.statements[1])


async def test_a_suggestion_that_no_longer_fits_falls_back_to_unmatched() -> None:
    session = FakeSession()
    session.execute_queue = [
        [
            make_transaction(
                match_status=PaymentMatchStatus.SUGGESTED,
                reference="Incoming transfer",
                counterparty_name="Halcyon Supplies",
            )
        ],
        [],
        [make_transaction(version=2)],
    ]

    result = await make_service(session).reconcile(ACCESS)

    assert result.unmatched == 1
    assert "match_status" in set_clause_of(session.statements[2])


async def test_the_candidate_query_narrows_by_the_same_conditions_as_the_rule() -> None:
    """It may narrow, never decide: the rule is applied again to what returns."""
    session = FakeSession()
    session.execute_queue = [[make_transaction()], []]

    await make_service(session).reconcile(ACCESS)

    criteria = where_of(session.statements[1])
    assert "orders.deleted_at IS NULL" in criteria
    assert "orders.status IN" in criteria
    assert "orders.total >=" in criteria
    assert "orders.total <=" in criteria
    assert "orders.placed_at <=" in criteria
    assert "orders.placed_at >=" in criteria


async def test_an_order_the_query_returned_is_still_put_to_the_rule() -> None:
    # The SQL cannot express "the payer wrote the number down", so a row that
    # survived the query can still fail the rule.
    session = FakeSession()
    session.execute_queue = [
        [make_transaction(reference="Incoming transfer", counterparty_name="Halcyon Supplies")],
        [candidate_row()],
    ]

    result = await make_service(session).reconcile(ACCESS)

    assert result.matched == 0
    assert result.unmatched == 1


# --- the summary -----------------------------------------------------------

#: A window the caller named, so the service asks no question about statements
#: and the grouped query is the first statement it builds.
NAMED_WINDOW = FinanceSummaryParams(
    **{"from": datetime(2026, 1, 1, tzinfo=UTC), "to": datetime(2026, 2, 1, tzinfo=UTC)}
)


async def test_the_summary_adds_the_flow_up_and_reports_the_balance() -> None:
    session = FakeSession()
    session.execute_queue = [
        [
            (TransactionDirection.CREDIT, PaymentMatchStatus.MATCHED, 2, Decimal("1800.00")),
            (TransactionDirection.CREDIT, PaymentMatchStatus.UNMATCHED, 1, Decimal("450.50")),
            (TransactionDirection.DEBIT, PaymentMatchStatus.UNMATCHED, 1, Decimal("3200.00")),
        ]
    ]

    result = await make_service(session).summary(ACCESS, NAMED_WINDOW)

    assert result.inflow == "2250.50"
    assert result.outflow == "3200.00"
    assert result.net == "-949.50"
    assert result.transaction_count == 4


async def test_every_state_is_reported_even_when_it_is_empty() -> None:
    """Two periods have to line up, so the shape cannot depend on the data."""
    session = FakeSession()
    session.execute_queue = [
        [(TransactionDirection.CREDIT, PaymentMatchStatus.MATCHED, 4, Decimal("1000.00"))]
    ]

    result = await make_service(session).summary(ACCESS, NAMED_WINDOW)

    assert [row.status for row in result.statuses] == [
        PaymentMatchStatus.UNMATCHED,
        PaymentMatchStatus.SUGGESTED,
        PaymentMatchStatus.MATCHED,
        PaymentMatchStatus.IGNORED,
    ]
    assert [row.amount for row in result.statuses] == ["0.00", "0.00", "1000.00", "0.00"]
    assert [row.share for row in result.statuses] == [0.0, 0.0, 1.0, 0.0]


async def test_a_share_is_rounded_to_four_decimals() -> None:
    session = FakeSession()
    session.execute_queue = [
        [
            (TransactionDirection.CREDIT, PaymentMatchStatus.MATCHED, 1, Decimal("10.00")),
            (TransactionDirection.CREDIT, PaymentMatchStatus.UNMATCHED, 2, Decimal("20.00")),
        ]
    ]

    result = await make_service(session).summary(ACCESS, NAMED_WINDOW)

    shares = {row.status: row.share for row in result.statuses}
    assert shares[PaymentMatchStatus.UNMATCHED] == 0.6667
    assert shares[PaymentMatchStatus.MATCHED] == 0.3333


async def test_an_empty_window_divides_by_nothing() -> None:
    session = FakeSession()

    result = await make_service(session).summary(ACCESS, NAMED_WINDOW)

    assert result.transaction_count == 0
    assert result.inflow == result.outflow == result.net == "0.00"
    assert all(row.share == 0.0 for row in result.statuses)


async def test_the_summary_window_is_half_open() -> None:
    # Two adjacent periods must not both claim the instant on their boundary.
    session = FakeSession()
    params = FinanceSummaryParams.model_validate(
        {"from": BOOKED_AT, "to": BOOKED_AT + timedelta(days=1)}
    )

    await make_service(session).summary(ACCESS, params)

    criteria = where_of(session.statements[0])
    assert "bank_transactions.booked_at >=" in criteria
    assert "bank_transactions.booked_at <" in criteria
    assert "bank_transactions.booked_at <=" not in criteria


async def test_the_summary_reads_every_figure_from_one_query() -> None:
    """Reading twice is how two halves of a report end up describing two
    different instants."""
    session = FakeSession()

    await make_service(session).summary(ACCESS, NAMED_WINDOW)

    assert len(session.statements) == 1


async def test_an_unnamed_window_uses_the_shared_fixed_default() -> None:
    """The default does not depend on imported statements or the current day."""
    session = FakeSession()

    result = await make_service(session).summary(ACCESS, FinanceSummaryParams())

    assert result.from_ == datetime(2026, 1, 1, tzinfo=UTC)
    assert result.to == datetime(2026, 2, 1, tzinfo=UTC)
    # The grouped query is the only read: no latest-statement lookup precedes it.
    assert len(session.statements) == 1


async def test_a_missing_bound_uses_the_shared_default_while_an_explicit_one_wins() -> None:
    lower_bound_session = FakeSession()
    lower_bound = FinanceSummaryParams.model_validate({"from": "2026-01-10T00:00:00Z"})

    lower_bound_result = await make_service(lower_bound_session).summary(ACCESS, lower_bound)

    assert lower_bound_result.from_ == datetime(2026, 1, 10, tzinfo=UTC)
    assert lower_bound_result.to == datetime(2026, 2, 1, tzinfo=UTC)

    upper_bound_session = FakeSession()
    upper_bound = FinanceSummaryParams.model_validate({"to": "2026-01-20T00:00:00Z"})

    upper_bound_result = await make_service(upper_bound_session).summary(ACCESS, upper_bound)

    assert upper_bound_result.from_ == datetime(2026, 1, 1, tzinfo=UTC)
    assert upper_bound_result.to == datetime(2026, 1, 20, tzinfo=UTC)
