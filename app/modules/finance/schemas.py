"""Wire contract of the finance endpoints.

Three things are pinned here rather than left to a default.

Every amount crosses the boundary as a string, in both directions. The client
runs on a language whose only number type cannot hold a decimal exactly, so an
amount that travelled as a JSON number would already have been rounded by the
time any code of ours saw it. That applies to a filter just as much as to a
balance: ``minAmount=19.99`` is the same trap as ``amount: 19.99``.

Nothing a client sends describes what the bank did. The lines of a statement
are the bank's account of money that has already moved, so no request body
here carries an amount, a date or a counterparty. What a client may state is
what a line *means* — which order it settles — and that is the whole of the
write surface.

And a transaction read on its own carries its candidates. The list is not
stored anywhere: a suggestion is a question about the present state of the
order book, and one computed last week would be answering a question about a
book that has since changed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, SortOrder
from app.core.responses import CamelModel
from app.core.serializers import Money, UtcDate, UtcDatetime
from app.db.enums import OrderStatus, PaymentMatchStatus, TransactionDirection
from app.modules.finance.types import (
    MAX_SEARCH_LENGTH,
    MONEY_STRING_PATTERN,
    StatementSortField,
    TransactionSortField,
)

__all__ = [
    "MAX_SUMMARY_DAYS",
    "BankStatementOut",
    "BankTransactionDetailOut",
    "BankTransactionOut",
    "FinanceSummaryOut",
    "FinanceSummaryParams",
    "ImportStatementOut",
    "MatchCandidateOut",
    "MatchStatusShare",
    "MatchTransactionRequest",
    "MoneyString",
    "ReconcileOut",
    "StatementListParams",
    "TransactionListParams",
]

#: Window a summary covers when the caller names none.

#: Widest window one summary may scan, so a single request cannot walk years
#: of ledger.
MAX_SUMMARY_DAYS = 366

#: An amount as it arrives from a client: a string, always.
MoneyString = Annotated[str, StringConstraints(strip_whitespace=True, pattern=MONEY_STRING_PATTERN)]

#: Optimistic locking counter as the client echoes it back.
Version = Annotated[int, Field(ge=1)]

#: A computed figure in the summary. Deliberately *not* the ``Money`` of a
#: stored amount: a persisted value is published in shortest exact form, while
#: a column of totals keeps its two decimals so the figures line up under each
#: other. The value is a string before it reaches this model.
SummaryMoney = str


class BankStatementOut(CamelModel):
    """A statement as the API publishes it."""

    id: uuid.UUID
    external_id: str
    account_label: str
    period_start: UtcDate
    period_end: UtcDate
    opening_balance: Money
    closing_balance: Money
    currency: str
    imported_at: UtcDatetime
    imported_by_id: uuid.UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class BankTransactionOut(CamelModel):
    """One line of a statement, and how far it got towards an order."""

    id: uuid.UUID
    statement_id: uuid.UUID
    external_id: str
    booked_at: UtcDatetime
    amount: Money
    currency: str
    direction: TransactionDirection
    counterparty_name: str
    counterparty_account: str | None
    reference: str
    match_status: PaymentMatchStatus
    matched_order_id: uuid.UUID | None
    matched_at: UtcDatetime | None
    matched_by_id: uuid.UUID | None
    version: int
    created_at: UtcDatetime
    updated_at: UtcDatetime


class MatchCandidateOut(CamelModel):
    """An order this payment might be settling.

    A candidate, not a decision: it is published precisely because the system
    could not choose, and the person reading it can.
    """

    order_id: uuid.UUID
    order_number: str
    status: OrderStatus
    total: Money
    currency: str
    contact_id: uuid.UUID | None
    #: The field the rule compared against, so a reader can check the answer.
    placed_at: UtcDatetime | None


class BankTransactionDetailOut(BankTransactionOut):
    """One transaction, read on its own, with whatever it might belong to.

    ``candidates`` is empty for anything the rule already settled — a matched
    line has an answer, and an unmatched one had none to offer.
    """

    candidates: list[MatchCandidateOut]


class ImportStatementOut(CamelModel):
    """Outcome of one ``POST /finance/statements/import``.

    The two numbers are what makes a repeated import legible: ``imported`` is
    what was new and ``skipped`` is everything already on file. A second import
    of an unchanged statement therefore reports nothing new and skips the lot,
    which is the visible form of the guarantee.
    """

    statement_id: uuid.UUID
    imported: int = Field(ge=0)
    skipped: int = Field(ge=0)


class ReconcileOut(CamelModel):
    """Outcome of one batch reconciliation.

    ``examined`` counts the lines the batch took in; the other four count
    where they ended up, and they add up to it. ``unmatched`` is reported
    rather than hidden because it is the honest measure of how well the rule
    is working, and ``ignored`` is the outgoing money, which is examined and
    filed rather than left out of the count.
    """

    examined: int = Field(ge=0)
    matched: int = Field(ge=0)
    suggested: int = Field(ge=0)
    unmatched: int = Field(ge=0)
    ignored: int = Field(ge=0)


class MatchStatusShare(CamelModel):
    """How much of the window sits in one reconciliation state."""

    status: PaymentMatchStatus
    count: int
    amount: SummaryMoney
    #: Share of the window's transactions, between zero and one, to four
    #: decimals. A rate rather than money, so a plain number is the right shape.
    share: float


class FinanceSummaryOut(CamelModel):
    """Body of ``GET /finance/summary``.

    All four states are always present, zero-filled where nothing fell into
    them: a reader comparing two periods needs the rows to line up, and a
    state that vanished when it emptied would make the shape of the answer
    depend on the data.
    """

    from_: UtcDatetime = Field(alias="from")
    to: UtcDatetime
    transaction_count: int
    inflow: SummaryMoney
    outflow: SummaryMoney
    net: SummaryMoney
    statuses: list[MatchStatusShare]


class MatchTransactionRequest(CamelModel):
    """Body of ``POST /finance/transactions/{id}/match``.

    Two fields and no more. The amount is not among them: it is what the bank
    reported, and an endpoint that let a client restate it would be an
    endpoint for making the books agree by typing.
    """

    order_id: uuid.UUID
    version: Version


class StatementListParams(CamelModel):
    """Query string of ``GET /finance/statements``."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    search: str | None = Field(default=None, min_length=1, max_length=MAX_SEARCH_LENGTH)
    sort_by: StatementSortField = "periodStart"
    sort_order: SortOrder = "desc"


class TransactionListParams(CamelModel):
    """Query string of ``GET /finance/transactions``.

    Grouped into a model rather than spelled out as a dozen handler arguments,
    which also puts the two cross-field rules next to the fields they
    constrain.
    """

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    search: str | None = Field(default=None, min_length=1, max_length=MAX_SEARCH_LENGTH)
    statement_id: uuid.UUID | None = None
    match_status: PaymentMatchStatus | None = None
    direction: TransactionDirection | None = None
    # A zone is required rather than assumed: "2026-01-05T00:00:00" means a
    # different instant in every office that sends it, and reading it as UTC
    # would answer a question the caller did not ask.
    booked_from: AwareDatetime | None = None
    booked_to: AwareDatetime | None = None
    min_amount: MoneyString | None = None
    max_amount: MoneyString | None = None
    sort_by: TransactionSortField = "bookedAt"
    sort_order: SortOrder = "desc"

    @model_validator(mode="after")
    def _require_ordered_bounds(self) -> Self:
        if (
            self.booked_from is not None
            and self.booked_to is not None
            and self.booked_from > self.booked_to
        ):
            message = "bookedFrom must not be later than bookedTo"
            raise ValueError(message)
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and Decimal(self.min_amount) > Decimal(self.max_amount)
        ):
            message = "minAmount must not exceed maxAmount"
            raise ValueError(message)
        return self


def _as_utc(value: datetime) -> datetime:
    """Reads a bound as UTC.

    A client may send ``2026-01-01``, which parses without a zone. Treating
    that as local time would move the window by the offset of whichever
    machine this process happens to run on.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class FinanceSummaryParams(CamelModel):
    """Query string of ``GET /finance/summary``.

    Both bounds stay optional, and neither is filled in here.

    They used to be resolved at validation time against the clock: ``to``
    became "now" and ``from`` a month before it. That made the answer to a
    question with no parameters depend on the day it was asked. The service
    resolves omitted bounds from the shared fixed reporting window instead,
    so every reporting module describes the same period.

    The checks below therefore apply only to a window the caller actually
    named. A caller who names one bound, or none, is making no claim to
    contradict.
    """

    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None

    @model_validator(mode="after")
    def _check_named_range(self) -> Self:
        if self.from_ is None or self.to is None:
            return self

        from_, to = _as_utc(self.from_), _as_utc(self.to)
        if from_ >= to:
            message = "from must be earlier than to"
            raise ValueError(message)
        if to - from_ > timedelta(days=MAX_SUMMARY_DAYS):
            message = f"The date range must not exceed {MAX_SUMMARY_DAYS} days"
            raise ValueError(message)
        return self

    @property
    def range_from(self) -> datetime | None:
        """Lower bound as the caller gave it, normalised to UTC."""
        return None if self.from_ is None else _as_utc(self.from_)

    @property
    def range_to(self) -> datetime | None:
        """Upper bound as the caller gave it, normalised to UTC."""
        return None if self.to is None else _as_utc(self.to)
