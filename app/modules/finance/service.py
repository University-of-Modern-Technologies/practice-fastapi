"""Finance rules.

Four of them shape almost every method here.

A statement is never authored: it is imported. The bank says what moved, and
the import is idempotent by identity — ``external_id`` is unique on both
tables, so pulling the same feed twice files nothing the second time. That
check deliberately ignores nothing at all: a line already on file is a line
already on file, whatever has since been decided about it.

Reconciliation is a guess, and the module never pretends otherwise. The rule
in ``matching.py`` is the whole of it; a query here may narrow by the same
conditions, never by different ones, and the outcome is decided by counting
candidates rather than by preferring one.

``MATCHED`` and ``matched_order_id`` stand or fall together. The database says
so too — there is a check constraint on the pair — and every write below sets
the two in one statement, because a row that claimed to be matched while
naming nothing is a row no reconciliation report can describe.

And every edit is guarded by the version the caller read, with the guard in
the ``WHERE`` clause of the statement itself, so two requests racing to
reconcile the same payment cannot both win.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Update, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.errors import ConflictError, NotFoundError, VersionConflictError
from app.core.filters import FilterBuilder
from app.core.paged_query import PagedQuery
from app.core.serializers import format_scaled_money
from app.db.enums import PaymentMatchStatus, TransactionDirection
from app.db.models.contact import Contact
from app.db.models.finance import BankStatement, BankTransaction
from app.db.models.order import Order
from app.events.dispatch import announcer, publish_after_commit
from app.events.types import DomainEvent, DomainEventPublisher, NoopPublisher
from app.modules.audit import AuditEvent, AuditService
from app.modules.finance.matching import (
    MATCH_AMOUNT_TOLERANCE,
    MATCH_WINDOW,
    MATCHABLE_ORDER_STATUSES,
    MatchCandidate,
    MatchSubject,
    amounts_match,
    outcome_for,
    select_candidates,
)
from app.modules.finance.provider import (
    BankProvider,
    ProviderStatement,
    ProviderTransaction,
    bank_provider_unavailable_error,
)
from app.modules.finance.schemas import (
    DEFAULT_SUMMARY_DAYS,
    BankStatementOut,
    BankTransactionDetailOut,
    BankTransactionOut,
    FinanceSummaryOut,
    FinanceSummaryParams,
    ImportStatementOut,
    MatchCandidateOut,
    MatchStatusShare,
    MatchTransactionRequest,
    ReconcileOut,
    StatementListParams,
    TransactionListParams,
)
from app.modules.finance.types import (
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
    StatementSortField,
    TransactionSortField,
)

__all__ = [
    "RECONCILE_BATCH_SIZE",
    "FinanceService",
    "to_statement_out",
    "to_transaction_out",
]

#: Columns a client may sort by, under the names the client uses. A lookup
#: rather than ``getattr``: only what is in these tables can reach an
#: ``ORDER BY``.
_TRANSACTION_SORTABLE: dict[TransactionSortField, InstrumentedAttribute[Any]] = {
    "bookedAt": BankTransaction.booked_at,
    "amount": BankTransaction.amount,
    "createdAt": BankTransaction.created_at,
}

_STATEMENT_SORTABLE: dict[StatementSortField, InstrumentedAttribute[Any]] = {
    "periodStart": BankStatement.period_start,
    "importedAt": BankStatement.imported_at,
    "createdAt": BankStatement.created_at,
}

_CONCURRENT_MESSAGE = "Transaction was modified by another request"

#: The states a batch reconciliation may still change. ``MATCHED`` is somebody's
#: answer and ``IGNORED`` is somebody's decision; re-deciding either behind
#: their back is what would make the button unusable.
_RECONCILABLE_STATUSES: tuple[PaymentMatchStatus, ...] = (
    PaymentMatchStatus.UNMATCHED,
    PaymentMatchStatus.SUGGESTED,
)

#: Upper bound on one reconciliation run. A deployment constant rather than a
#: client parameter: the work is bounded by what this system can absorb inside
#: one request transaction, not by what a caller would like.
RECONCILE_BATCH_SIZE = 200

#: Denominator of a share: four decimal places.
_RATE_PRECISION = 10_000

#: The four states, always reported in this order so two periods line up.
_SUMMARY_STATUSES: tuple[PaymentMatchStatus, ...] = (
    PaymentMatchStatus.UNMATCHED,
    PaymentMatchStatus.SUGGESTED,
    PaymentMatchStatus.MATCHED,
    PaymentMatchStatus.IGNORED,
)


def _as_utc_instant(value: date | datetime) -> datetime:
    """A period bound as an instant at UTC midnight.

    ``period_start`` and ``period_end`` are calendar days. Reading a day as a
    local instant would move the window by the offset of whichever machine
    this process happens to run on, which is the drift this module exists to
    be free of.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def to_statement_out(statement: BankStatement) -> BankStatementOut:
    """Renders a stored statement in the shape the API publishes."""
    return BankStatementOut(
        id=statement.id,
        external_id=statement.external_id,
        account_label=statement.account_label,
        period_start=statement.period_start,
        period_end=statement.period_end,
        opening_balance=statement.opening_balance,
        closing_balance=statement.closing_balance,
        currency=statement.currency,
        imported_at=statement.imported_at,
        imported_by_id=statement.imported_by_id,
        created_at=statement.created_at,
        updated_at=statement.updated_at,
    )


def to_transaction_out(transaction: BankTransaction) -> BankTransactionOut:
    """Renders a stored transaction in the shape the API publishes."""
    return BankTransactionOut(
        id=transaction.id,
        statement_id=transaction.statement_id,
        external_id=transaction.external_id,
        booked_at=transaction.booked_at,
        amount=transaction.amount,
        currency=transaction.currency,
        direction=transaction.direction,
        counterparty_name=transaction.counterparty_name,
        counterparty_account=transaction.counterparty_account,
        reference=transaction.reference,
        match_status=transaction.match_status,
        matched_order_id=transaction.matched_order_id,
        matched_at=transaction.matched_at,
        matched_by_id=transaction.matched_by_id,
        version=transaction.version,
        created_at=transaction.created_at,
        updated_at=transaction.updated_at,
    )


def _snapshot(value: BankTransactionOut | BankStatementOut) -> dict[str, Any]:
    """A record as a plain document, for the trail and the event stream."""
    return value.model_dump(by_alias=True, mode="json")


def _is_external_id_conflict(error: IntegrityError) -> bool:
    """Whether the insert lost a race on the bank's own identifier."""
    return "external_id" in str(error.orig).lower()


def _share(count: int, total: int) -> float:
    """What fraction of the window one state holds, to four decimals.

    A rate, not money, so a plain number is the right shape. ``math.floor`` of
    the half-shifted value rather than ``round``: the built-in rounds halves to
    the nearest even number, which would report a different share than the
    sibling backend on exactly the values that end in a five.
    """
    if total <= 0:
        return 0.0
    return math.floor(count / total * _RATE_PRECISION + 0.5) / _RATE_PRECISION


class _StatementPage(PagedQuery[BankStatement, StatementListParams, BankStatementOut]):
    """One page of statements."""

    def _model(self) -> type[BankStatement]:
        return BankStatement

    def _build_filters(self, params: StatementListParams) -> list[ColumnElement[bool]]:
        return (
            FilterBuilder()
            .search(
                params.search,
                [BankStatement.account_label, BankStatement.external_id],
                escape=True,
            )
            .build()
        )

    def _order_by(self, params: StatementListParams) -> Sequence[ColumnElement[Any]]:
        column = _STATEMENT_SORTABLE[params.sort_by]
        primary = column.asc() if params.sort_order == "asc" else column.desc()
        return (primary, BankStatement.id.asc())

    def _to_dto(self, row: BankStatement) -> BankStatementOut:
        return to_statement_out(row)


class _TransactionPage(PagedQuery[BankTransaction, TransactionListParams, BankTransactionOut]):
    """One page of the ledger."""

    def _model(self) -> type[BankTransaction]:
        return BankTransaction

    def _build_filters(self, params: TransactionListParams) -> list[ColumnElement[bool]]:
        return (
            FilterBuilder()
            .equals(BankTransaction.statement_id, params.statement_id)
            .equals(BankTransaction.match_status, params.match_status)
            .equals(BankTransaction.direction, params.direction)
            # What a payer wrote and who they said they were: the two things
            # anybody actually searches a ledger by when hunting a payment.
            .search(
                params.search,
                [BankTransaction.reference, BankTransaction.counterparty_name],
                escape=True,
            )
            .range(BankTransaction.booked_at, params.booked_from, params.booked_to)
            .range(
                BankTransaction.amount,
                Decimal(params.min_amount) if params.min_amount is not None else None,
                Decimal(params.max_amount) if params.max_amount is not None else None,
            )
            .build()
        )

    def _order_by(self, params: TransactionListParams) -> Sequence[ColumnElement[Any]]:
        column = _TRANSACTION_SORTABLE[params.sort_by]
        primary = column.asc() if params.sort_order == "asc" else column.desc()
        # The id breaks ties: two lines booked in the same minute for the same
        # amount would otherwise page in whatever order the planner felt like.
        return (primary, BankTransaction.id.asc())

    def _to_dto(self, row: BankTransaction) -> BankTransactionOut:
        return to_transaction_out(row)


class FinanceService:
    """Imports what the bank reported, and works out what it was for."""

    def __init__(
        self,
        session: AsyncSession,
        provider: BankProvider,
        events: DomainEventPublisher | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        self._events: DomainEventPublisher = events if events is not None else NoopPublisher()
        # The trail is written on the very session the change is written on, so
        # a rolled back import cannot leave entries claiming it happened.
        self._audit = audit if audit is not None else AuditService(session)

    # --- reading -----------------------------------------------------------

    async def list_statements(
        self, access: FinanceAccess, params: StatementListParams
    ) -> tuple[list[BankStatementOut], int]:
        """One page of statements, plus the size of the whole filtered set."""
        del access
        return await _StatementPage(self._session).run(params)

    async def list_transactions(
        self, access: FinanceAccess, params: TransactionListParams
    ) -> tuple[list[BankTransactionOut], int]:
        """One page of the ledger, plus the size of the whole filtered set.

        A ``statementId`` that names nothing is reported rather than answered
        with an empty page: a caller filtering by a statement they believe in
        has asked a question about it, and "no rows" would look like an answer.
        """
        del access
        if params.statement_id is not None:
            await self._require_statement(params.statement_id)
        return await _TransactionPage(self._session).run(params)

    async def get_transaction(
        self, access: FinanceAccess, transaction_id: uuid.UUID
    ) -> BankTransactionDetailOut:
        """One transaction, with the orders it might belong to.

        The candidates are recomputed here rather than read back from a column
        deliberately: a suggestion is a statement about the order book as it
        stands, and one saved a week ago would be describing a book that has
        since moved on. Only a ``SUGGESTED`` line has any — the others are
        either already answered or were never in question.
        """
        del access
        transaction = await self._require_transaction(transaction_id)
        candidates: list[MatchCandidate] = []
        if transaction.match_status is PaymentMatchStatus.SUGGESTED:
            candidates = await self._candidates_for(transaction)

        return BankTransactionDetailOut(
            **to_transaction_out(transaction).model_dump(),
            candidates=[
                MatchCandidateOut(
                    order_id=candidate.order_id,
                    order_number=candidate.order_number,
                    status=candidate.status,
                    total=candidate.total,
                    currency=candidate.currency,
                    contact_id=candidate.contact_id,
                    placed_at=candidate.placed_at,
                )
                for candidate in candidates
            ],
        )

    async def summary(
        self, access: FinanceAccess, params: FinanceSummaryParams
    ) -> FinanceSummaryOut:
        """What moved over the window, and how much of it is settled.

        One grouped query rather than one query per figure: the same rows
        answer every number below, and reading them twice is how two halves of
        a report end up describing two different instants.
        """
        del access
        window_from, window_to = await self._resolve_summary_window(params)
        rows = (
            await self._session.execute(
                select(
                    BankTransaction.direction,
                    BankTransaction.match_status,
                    func.count(),
                    func.coalesce(func.sum(BankTransaction.amount), 0),
                )
                # Half-open, as every window in this codebase is: two adjacent
                # periods must not both claim the instant on their boundary.
                .where(
                    BankTransaction.booked_at >= window_from,
                    BankTransaction.booked_at < window_to,
                )
                .group_by(BankTransaction.direction, BankTransaction.match_status)
            )
        ).all()

        inflow = Decimal(0)
        outflow = Decimal(0)
        counts: dict[PaymentMatchStatus, int] = dict.fromkeys(_SUMMARY_STATUSES, 0)
        amounts: dict[PaymentMatchStatus, Decimal] = dict.fromkeys(_SUMMARY_STATUSES, Decimal(0))

        for direction, status, count, total in rows:
            amount = Decimal(total)
            if direction is TransactionDirection.CREDIT:
                inflow += amount
            else:
                outflow += amount
            counts[status] = counts.get(status, 0) + int(count)
            amounts[status] = amounts.get(status, Decimal(0)) + amount

        examined = sum(counts.values())
        return FinanceSummaryOut(
            from_=window_from,
            to=window_to,
            transaction_count=examined,
            inflow=format_scaled_money(inflow),
            outflow=format_scaled_money(outflow),
            net=format_scaled_money(inflow - outflow),
            statuses=[
                MatchStatusShare(
                    status=status,
                    count=counts[status],
                    amount=format_scaled_money(amounts[status]),
                    share=_share(counts[status], examined),
                )
                for status in _SUMMARY_STATUSES
            ],
        )

    async def _resolve_summary_window(
        self, params: FinanceSummaryParams
    ) -> tuple[datetime, datetime]:
        """Fills in whichever bound the caller left out.

        From the newest statement on file, not from the clock. A ledger is a
        record of periods that happened, and "the summary, please" means the
        period there is data for — asked in March, or asked two years later.
        Defaulting to the last thirty days instead makes the module answer
        honestly with zeroes and look broken, which is the worse of the two
        ways to be right.

        With nothing imported at all there is no period to name, and the window
        falls back to the recent past. Either way the answer is empty, so the
        fallback settles only what the report echoes back.
        """
        given_from, given_to = params.range_from, params.range_to
        if given_from is not None and given_to is not None:
            return given_from, given_to

        latest = (
            await self._session.execute(
                select(BankStatement.period_start, BankStatement.period_end)
                .order_by(BankStatement.period_start.desc(), BankStatement.id.asc())
                .limit(1)
            )
        ).first()

        now = datetime.now(tz=UTC)
        if latest is None:
            to = given_to if given_to is not None else now
            return (
                given_from if given_from is not None else to - timedelta(days=DEFAULT_SUMMARY_DAYS),
                to,
            )

        period_start, period_end = latest
        # The period is inclusive of its last day; the window is half-open, so
        # the upper bound is the midnight after it rather than the day itself.
        return (
            given_from if given_from is not None else _as_utc_instant(period_start),
            given_to if given_to is not None else _as_utc_instant(period_end) + timedelta(days=1),
        )

    # --- importing ---------------------------------------------------------

    async def import_statement(self, access: FinanceAccess) -> ImportStatementOut:
        """Pulls a statement from the bank and files whatever is new.

        Idempotent by identity rather than by bookkeeping: every line carries
        the bank's own ``external_id``, that column is unique, and everything
        already on file is skipped before an insert is attempted. Nothing here
        depends on when the previous import ran, so a repeated pull, an
        overlapping period and a pull replayed after a crash all converge on
        the same ledger.

        A duplicate is never an error, which is why the rows go in one
        savepoint at a time rather than in one statement. The lookup above
        races with a concurrent import, and in PostgreSQL a unique violation
        poisons the whole transaction: batched, a single line somebody else
        filed a second earlier would take the entire import down with it. One
        savepoint per row means the collision rolls back exactly that row, is
        counted as skipped, and its neighbours survive.

        An imported line is filed ``UNMATCHED`` and nothing else. Reconciling
        it is a separate decision, with its own endpoint and its own audit
        entry — an import that also guessed would leave no way to tell what the
        bank said from what we inferred.
        """
        feed = await self._fetch_statement()
        statement, created = await self._statement_row(access, feed)

        unique = self._deduplicate(feed.transactions)
        known = await self._existing_external_ids(unique)

        imported = 0
        for item in unique.values():
            if item.external_id in known:
                continue
            if await self._insert_transaction(statement.id, item):
                imported += 1

        if created or imported:
            changes = {"after": _snapshot(to_statement_out(statement))}
            await self._record(
                access, STATEMENT_IMPORTED, STATEMENT_ENTITY_TYPE, statement.id, changes
            )
            self._announce(STATEMENT_IMPORTED, STATEMENT_ENTITY_TYPE, statement.id, access, changes)

        return ImportStatementOut(
            statement_id=statement.id,
            imported=imported,
            skipped=len(feed.transactions) - imported,
        )

    # --- reconciling -------------------------------------------------------

    async def match(
        self, access: FinanceAccess, transaction_id: uuid.UUID, data: MatchTransactionRequest
    ) -> BankTransactionOut:
        """Attributes a payment to an order, because a person said so.

        The four conditions of the automatic rule are deliberately *not*
        applied here beyond the amount. A person matching by hand is doing it
        precisely because the rule could not: the number was never quoted, the
        payment arrived five months late, the order is not in a state the rule
        will touch. The one condition that survives is the amount, because a
        payment attributed to an order it cannot possibly settle is a mistake
        rather than a judgement, and the tolerance already allows for the cent
        a bank fee costs.
        """
        existing = await self._require_transaction(transaction_id)
        self._assert_version(existing.version, data.version)
        if existing.match_status is PaymentMatchStatus.MATCHED:
            raise ConflictError(
                "Transaction is already matched to an order", TRANSACTION_ALREADY_MATCHED
            )

        order = await self._require_order(data.order_id)
        if not amounts_match(existing.amount, order.total):
            raise ConflictError(
                "The transaction amount does not match the order total",
                TRANSACTION_AMOUNT_MISMATCH,
            )

        before = to_transaction_out(existing)
        after = await self._write(
            transaction_id,
            data.version,
            self._matched_values(order.id, access.actor_id),
        )
        await self._report(access, TRANSACTION_MATCHED, transaction_id, before, after)
        return after

    async def unmatch(
        self, access: FinanceAccess, transaction_id: uuid.UUID, version: int
    ) -> BankTransactionOut:
        """Takes a payment back off an order.

        The line returns to ``UNMATCHED`` rather than to whatever it was before
        somebody matched it: undoing an attribution puts the payment back in
        the queue of things to decide, and restoring a stale ``SUGGESTED`` list
        would put a week-old guess back in front of the next person to look.
        """
        existing = await self._require_transaction(transaction_id)
        self._assert_version(existing.version, version)
        if existing.match_status is not PaymentMatchStatus.MATCHED:
            raise ConflictError("Transaction is not matched to an order", TRANSACTION_NOT_MATCHED)

        before = to_transaction_out(existing)
        after = await self._write(transaction_id, version, self._unmatched_values())
        await self._report(access, TRANSACTION_UNMATCHED, transaction_id, before, after)
        return after

    async def reconcile(self, access: FinanceAccess) -> ReconcileOut:
        """Applies the rule to everything still waiting on it.

        Outgoing lines are read in with the rest. The rule is never run over
        them — a payment we made is not settling an order somebody placed with
        us — but they are filed as ``IGNORED``, which is the decision rather
        than an omission: rent and payroll are real movements that no order
        will ever explain. Leaving them out would make ``IGNORED`` a state
        nothing can reach, and would make ``examined`` describe half the batch
        while calling itself the whole of it.

        Nothing already decided is touched: a line somebody matched by hand is
        an answer, a line somebody ignored is a decision, and a batch job that
        overrode either is a batch job people stop pressing.
        """
        pending = (
            (
                await self._session.execute(
                    select(BankTransaction)
                    .where(
                        BankTransaction.match_status.in_(_RECONCILABLE_STATUSES),
                    )
                    .order_by(BankTransaction.booked_at.asc(), BankTransaction.id.asc())
                    .limit(RECONCILE_BATCH_SIZE)
                )
            )
            .scalars()
            .all()
        )

        tally: dict[PaymentMatchStatus, int] = dict.fromkeys(_RECONCILABLE_STATUSES, 0)
        tally[PaymentMatchStatus.MATCHED] = 0
        tally[PaymentMatchStatus.IGNORED] = 0
        for transaction in pending:
            outcome = await self._reconcile_one(access, transaction)
            tally[outcome] = tally.get(outcome, 0) + 1

        return ReconcileOut(
            examined=len(pending),
            matched=tally[PaymentMatchStatus.MATCHED],
            suggested=tally[PaymentMatchStatus.SUGGESTED],
            unmatched=tally[PaymentMatchStatus.UNMATCHED],
            ignored=tally[PaymentMatchStatus.IGNORED],
        )

    async def _reconcile_one(
        self, access: FinanceAccess, transaction: BankTransaction
    ) -> PaymentMatchStatus:
        """Runs the rule over one line and files whatever it concluded."""
        if transaction.direction is not TransactionDirection.CREDIT:
            # Money going out is filed rather than judged, and filing it is
            # silent for the same reason the two undecided states are: nothing
            # was concluded about an order.
            if transaction.match_status is not PaymentMatchStatus.IGNORED:
                await self._write(
                    transaction.id,
                    transaction.version,
                    {"match_status": PaymentMatchStatus.IGNORED},
                )
            return PaymentMatchStatus.IGNORED

        candidates = await self._candidates_for(transaction)
        outcome = outcome_for(candidates)

        if outcome is PaymentMatchStatus.MATCHED:
            before = to_transaction_out(transaction)
            after = await self._write(
                transaction.id,
                transaction.version,
                self._matched_values(candidates[0].order_id, access.actor_id),
            )
            await self._report(access, TRANSACTION_MATCHED, transaction.id, before, after)
            return outcome

        if outcome is not transaction.match_status:
            # A change between "nothing fits" and "several might" is not an
            # event: nothing was decided, and a stream that announced every
            # re-run of the rule would drown the two announcements that matter.
            await self._write(transaction.id, transaction.version, {"match_status": outcome})
        return outcome

    # --- the rule, against the order book ----------------------------------

    async def _candidates_for(self, transaction: BankTransaction) -> list[MatchCandidate]:
        """Every order the rule accepts for this payment, oldest first.

        The query narrows by three of the four conditions — state, amount,
        window — purely so the rule is not handed the whole order book. It
        cannot decide anything the rule would not: ``select_candidates``
        applies all four again to what comes back, and it is the statement of
        record.
        """
        if transaction.direction is not TransactionDirection.CREDIT:
            return []

        rows = (
            await self._session.execute(
                select(
                    Order.id,
                    Order.order_number,
                    Order.status,
                    Order.total,
                    Order.currency,
                    Order.contact_id,
                    Order.placed_at,
                    Contact.first_name,
                    Contact.last_name,
                    Contact.company,
                )
                .outerjoin(Contact, Order.contact_id == Contact.id)
                .where(
                    Order.deleted_at.is_(None),
                    Order.status.in_(MATCHABLE_ORDER_STATUSES),
                    Order.total >= transaction.amount - MATCH_AMOUNT_TOLERANCE,
                    Order.total <= transaction.amount + MATCH_AMOUNT_TOLERANCE,
                    Order.placed_at <= transaction.booked_at,
                    Order.placed_at >= transaction.booked_at - MATCH_WINDOW,
                )
                # Oldest first: when two orders fit equally, the one that has
                # been waiting longer is the one a person would name.
                .order_by(Order.placed_at.asc(), Order.id.asc())
            )
        ).all()

        candidates = [
            MatchCandidate(
                order_id=row[0],
                order_number=row[1],
                status=row[2],
                total=row[3],
                currency=row[4],
                contact_id=row[5],
                placed_at=row[6],
                contact_name=self._contact_name(row[7], row[8]),
                contact_company=row[9],
            )
            for row in rows
        ]
        subject = MatchSubject(
            amount=transaction.amount,
            booked_at=transaction.booked_at,
            reference=transaction.reference,
            counterparty_name=transaction.counterparty_name,
        )
        return select_candidates(subject, candidates)

    @staticmethod
    def _contact_name(first_name: str | None, last_name: str | None) -> str | None:
        """The customer as a person's name, or nothing if the order has none."""
        parts = [part for part in (first_name, last_name) if part]
        return " ".join(parts) if parts else None

    # --- writing -----------------------------------------------------------

    @staticmethod
    def _matched_values(order_id: uuid.UUID, actor_id: uuid.UUID) -> dict[str, Any]:
        """The four columns that say "this payment settles that order".

        Set together, in one statement, because the database refuses the halves
        separately: a check constraint pairs ``MATCHED`` with an order, and
        that is the invariant rather than a formality.
        """
        return {
            "match_status": PaymentMatchStatus.MATCHED,
            "matched_order_id": order_id,
            "matched_at": datetime.now(tz=UTC),
            "matched_by_id": actor_id,
        }

    @staticmethod
    def _unmatched_values() -> dict[str, Any]:
        """The same four columns, cleared together for the same reason."""
        return {
            "match_status": PaymentMatchStatus.UNMATCHED,
            "matched_order_id": None,
            "matched_at": None,
            "matched_by_id": None,
        }

    async def _write(
        self, transaction_id: uuid.UUID, version: int, values: dict[str, Any]
    ) -> BankTransactionOut:
        """Applies a guarded write and returns the row it produced.

        The guard repeats the version inside the statement itself. Re-checking
        in Python would leave a window in which another request could slip a
        match in between the read and the write, and the loser of that race has
        to be told rather than silently overwrite the winner.
        """
        statement: Update = (
            update(BankTransaction)
            .where(BankTransaction.id == transaction_id, BankTransaction.version == version)
            .values(**values, version=BankTransaction.version + 1)
            .returning(BankTransaction)
            # `populate_existing` matters: the row just read is already in the
            # identity map, and without it the ORM would hand back that stale
            # instance instead of the values the database returned.
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        written = (await self._session.execute(statement)).scalars().first()
        if written is None:
            raise VersionConflictError(_CONCURRENT_MESSAGE, TRANSACTION_CONCURRENT_MODIFICATION)
        return to_transaction_out(written)

    async def _fetch_statement(self) -> ProviderStatement:
        """Asks the bank for a statement, or reports that it could not.

        Every failure of the upstream collapses into one 502 here rather than
        escaping as whatever the transport happened to raise: a caller of our
        API learns that the feed is unavailable, and the detail of *why* stays
        in the log on our side of the boundary.
        """
        try:
            return await self._provider.fetch_statement()
        except Exception as error:
            raise bank_provider_unavailable_error() from error

    async def _statement_row(
        self, access: FinanceAccess, feed: ProviderStatement
    ) -> tuple[BankStatement, bool]:
        """The stored statement for this feed, filing it if it is new.

        Returns whether it had to be created, because that is what decides
        whether an import is an event at all: a pull that found everything
        already on file changed nothing and announces nothing.
        """
        existing = (
            (
                await self._session.execute(
                    select(BankStatement).where(BankStatement.external_id == feed.external_id)
                )
            )
            .scalars()
            .one_or_none()
        )
        if existing is not None:
            return existing, False

        statement = BankStatement(
            id=uuid.uuid4(),
            external_id=feed.external_id,
            account_label=feed.account_label,
            period_start=feed.period_start,
            period_end=feed.period_end,
            opening_balance=feed.opening_balance,
            closing_balance=feed.closing_balance,
            currency=feed.currency,
            imported_by_id=access.actor_id,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(statement)
                await self._session.flush()
        except IntegrityError as error:
            if not _is_external_id_conflict(error):
                raise
            # Another import filed this very period between the lookup and the
            # write. Reported rather than absorbed: the caller retries, and the
            # retry finds the statement above and is a no-op.
            raise ConflictError(
                "This statement has already been imported", STATEMENT_DUPLICATE_EXTERNAL_ID
            ) from error

        await self._session.refresh(statement)
        return statement, True

    @staticmethod
    def _deduplicate(
        batch: Iterable[ProviderTransaction],
    ) -> dict[str, ProviderTransaction]:
        """Collapses a batch onto its identifiers, keeping the first mention.

        The first rather than the last on purpose: a bank that repeats a line
        is repeating itself, and preferring the later copy would make the
        import depend on the order of a list nobody promised to order.
        """
        unique: dict[str, ProviderTransaction] = {}
        for item in batch:
            unique.setdefault(item.external_id, item)
        return unique

    async def _existing_external_ids(self, unique: dict[str, ProviderTransaction]) -> set[str]:
        """Which of these lines are already on file.

        One query for the whole batch rather than one per line: an import that
        issues a lookup per row turns a routine pull into a few hundred round
        trips, and the set it builds is the same either way.
        """
        if not unique:
            return set()

        result = await self._session.execute(
            select(BankTransaction.external_id).where(
                BankTransaction.external_id.in_(unique.keys())
            )
        )
        return set(result.scalars().all())

    async def _insert_transaction(self, statement_id: uuid.UUID, item: ProviderTransaction) -> bool:
        """Files one line, or reports that somebody beat us to it.

        Nothing about reconciliation is written: the bank knows what arrived,
        not what it was for, and a line arrives ``UNMATCHED`` by the column
        default of the table.
        """
        transaction = BankTransaction(
            id=uuid.uuid4(),
            statement_id=statement_id,
            external_id=item.external_id,
            booked_at=item.booked_at,
            amount=item.amount,
            currency=item.currency,
            direction=item.direction,
            counterparty_name=item.counterparty_name,
            counterparty_account=item.counterparty_account,
            reference=item.reference,
            match_status=PaymentMatchStatus.UNMATCHED,
            matched_order_id=None,
            matched_at=None,
            matched_by_id=None,
            version=1,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(transaction)
                await self._session.flush()
        except IntegrityError as error:
            if not _is_external_id_conflict(error):
                raise
            return False
        return True

    # --- lookups -----------------------------------------------------------

    async def _require_transaction(self, transaction_id: uuid.UUID) -> BankTransaction:
        transaction = (
            (
                await self._session.execute(
                    select(BankTransaction).where(BankTransaction.id == transaction_id)
                )
            )
            .scalars()
            .one_or_none()
        )
        if transaction is None:
            raise NotFoundError("Transaction not found", TRANSACTION_NOT_FOUND)
        return transaction

    async def _require_statement(self, statement_id: uuid.UUID) -> uuid.UUID:
        found = await self._session.scalar(
            select(BankStatement.id).where(BankStatement.id == statement_id)
        )
        if found is None:
            raise NotFoundError("Statement not found", STATEMENT_NOT_FOUND)
        return statement_id

    async def _require_order(self, order_id: uuid.UUID) -> Order:
        """The order a person is attributing a payment to.

        Reported with its own code rather than the orders module's
        ``ORDER_NOT_FOUND``: the client is inside a reconciliation workflow,
        and a code that named the other module would send it to re-read the
        wrong resource.
        """
        order = (
            (
                await self._session.execute(
                    select(Order).where(Order.id == order_id, Order.deleted_at.is_(None))
                )
            )
            .scalars()
            .one_or_none()
        )
        if order is None:
            raise NotFoundError("Order not found", TRANSACTION_ORDER_NOT_FOUND)
        return order

    @staticmethod
    def _assert_version(actual: int, expected: int) -> None:
        if actual != expected:
            raise VersionConflictError(_CONCURRENT_MESSAGE, TRANSACTION_CONCURRENT_MODIFICATION)

    # --- telling everybody else --------------------------------------------

    async def _report(
        self,
        access: FinanceAccess,
        action: str,
        transaction_id: uuid.UUID,
        before: BankTransactionOut,
        after: BankTransactionOut,
    ) -> None:
        """Writes the trail entry and announces the change, in that order."""
        changes = {"before": _snapshot(before), "after": _snapshot(after)}
        await self._record(access, action, TRANSACTION_ENTITY_TYPE, transaction_id, changes)
        self._announce(action, TRANSACTION_ENTITY_TYPE, transaction_id, access, changes)

    async def _record(
        self,
        access: FinanceAccess,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        changes: dict[str, Any],
    ) -> None:
        await self._audit.record(
            AuditEvent(
                actor_id=access.actor_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                changes=changes,
                ip_address=access.ip_address,
            )
        )

    def _announce(
        self,
        event_type: str,
        entity_type: str,
        entity_id: uuid.UUID,
        access: FinanceAccess,
        payload: Any,
    ) -> None:
        """Tells the secondary consumers what happened, once it has happened.

        Delivery waits for the session's commit: the request transaction closes
        after the handler returns, so announcing here would report a change
        that a later failure could still undo. A change that is written must
        then be reported as a success even if the event stream is unreachable,
        so a misbehaving publisher stays contained.
        """
        publish_after_commit(
            self._session,
            announcer(
                self._events,
                DomainEvent(
                    event_type=event_type,
                    entity_type=entity_type,
                    entity_id=str(entity_id),
                    actor_id=str(access.actor_id),
                    payload=payload,
                ),
            ),
        )
