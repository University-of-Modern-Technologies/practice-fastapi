"""In-repo stand-in for the bank feed.

The default configuration names no bank, and without this the module would be
dead on a fresh checkout: nothing to import, nothing to reconcile, nothing to
disagree about. The stub keeps the system runnable end to end with no account,
no key and no network.

It is not, however, merely a placeholder. What an import files is visible
through the API a moment later, which makes this table shared data rather than
an implementation detail — the same twelve lines have to come out of both
backends. So the fixture is fixed, it is generated from constants rather than
from the clock, and it is arranged so that every branch of the reconciliation
rule is reachable from it:

* ``0001`` to ``0003`` quote an order number and pay it to the cent;
* ``0004`` is a cent short: inside the tolerance, not equal to it;
* ``0005`` quotes no number at all, and the payer is named as the customer;
* ``0006`` has an amount and a reference that fit nothing;
* ``0007`` and ``0008`` share an amount and a payer and name no order, which
  is the whole of what makes a suggestion a suggestion;
* ``0009`` to ``0011`` are money going out, which is never reconciled;
* ``0012`` pays an order that was raised long afterwards.

The last line earns its place: without it the ninety-day window is a rule that
has been written down but never once exercised.

The order numbers the references quote are the ones this system allocates.
Whether a given line actually reaches ``MATCHED`` therefore depends on which
orders exist when the reconciliation runs — which is the honest behaviour of a
bank feed, and exactly the situation the module exists to handle.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.db.enums import TransactionDirection
from app.modules.finance.provider import ProviderStatement, ProviderTransaction

__all__ = [
    "STUB_BANK_PROVIDER_NAME",
    "STUB_OPENING_BALANCE",
    "STUB_STATEMENT_EXTERNAL_ID",
    "STUB_TRANSACTION_COUNT",
    "StubBankProvider",
    "create_stub_bank_provider",
    "stub_statement",
]

STUB_BANK_PROVIDER_NAME = "stub"

STUB_STATEMENT_EXTERNAL_ID = "stub-stmt-2026-01"
STUB_ACCOUNT_LABEL = "Operating account"
STUB_PERIOD_START = date(2026, 1, 1)
STUB_PERIOD_END = date(2026, 1, 31)
STUB_CURRENCY = "USD"
STUB_OPENING_BALANCE = Decimal("10000.00")

#: First line of the statement. Fixed, so a second import of the same feed
#: files nothing rather than merely being likely to.
_ANCHOR = datetime(2026, 1, 5, 10, 0, 0, tzinfo=UTC)

#: Spacing between consecutive lines, counting forwards.
_STEP = timedelta(days=2)

_CREDIT = TransactionDirection.CREDIT
_DEBIT = TransactionDirection.DEBIT

#: The payers, named once so a line of the table stays readable and so the
#: two lines that have to share a payer cannot drift apart by a typo.
_NORTH = "Alex North"
_CEDAR = "Casey Cedar"
_BLUE = "Jordan Blue"

_NORTH_ACCOUNT = "UA903052990000026007233566001"
_CEDAR_ACCOUNT = "UA903052990000026007233566002"
_BLUE_ACCOUNT = "UA903052990000026007233566003"

#: The statement as data: direction, amount, payer, account, reference. The
#: order of the rows is the order of the identifiers ``stub-txn-0001`` upwards
#: and of the booking dates, so the table reads as the account does.
_LINES: tuple[tuple[TransactionDirection, str, str, str | None, str], ...] = (
    (_CREDIT, "1800.00", _NORTH, _NORTH_ACCOUNT, "Payment for ORD-2026-0001"),
    (_CREDIT, "2400.00", _CEDAR, _CEDAR_ACCOUNT, "Invoice ORD-2026-0002"),
    (_CREDIT, "450.00", _BLUE, _BLUE_ACCOUNT, "ORD-2026-0003"),
    # A cent short of the order it names: the tolerance exists for this line.
    (_CREDIT, "1799.99", _NORTH, _NORTH_ACCOUNT, "Part payment ord-2026-0001"),
    # Nothing to key on but the payer's own name.
    (_CREDIT, "450.00", _BLUE, _BLUE_ACCOUNT, "Monthly settlement"),
    # Fits nothing, and stays that way.
    (_CREDIT, "275.50", "Halcyon Supplies", None, "Incoming transfer"),
    # Twice the same payer for the same amount, with nothing to tell them apart.
    (_CREDIT, "990.00", _NORTH, _NORTH_ACCOUNT, "Bank transfer"),
    (_CREDIT, "990.00", _NORTH, _NORTH_ACCOUNT, "Bank transfer"),
    (_DEBIT, "3200.00", "Riverside Property", None, "Office rent January 2026"),
    (_DEBIT, "5400.00", "Payroll clearing", None, "Payroll January 2026"),
    (_DEBIT, "780.00", "Aurora Consulting", None, "Professional services January"),
    # An advance against an order raised a quarter later: outside the window.
    (_CREDIT, "1250.00", _CEDAR, _CEDAR_ACCOUNT, "Advance for ORD-2026-0012"),
)

#: How many lines one import brings in. Derived rather than repeated, so the
#: table above stays the only place the fixture is stated.
STUB_TRANSACTION_COUNT = len(_LINES)


def _transaction(index: int) -> ProviderTransaction:
    direction, amount, counterparty, account, reference = _LINES[index]
    return ProviderTransaction(
        external_id=f"stub-txn-{index + 1:04d}",
        booked_at=_ANCHOR + _STEP * index,
        amount=Decimal(amount),
        currency=STUB_CURRENCY,
        direction=direction,
        counterparty_name=counterparty,
        counterparty_account=account,
        reference=reference,
    )


def _closing_balance(transactions: tuple[ProviderTransaction, ...]) -> Decimal:
    """What the account is left holding: the opening balance plus the flow.

    Computed from the lines rather than written down beside them, because a
    balance quoted as a constant is one that goes quietly wrong the first time
    a line is edited.
    """
    balance = STUB_OPENING_BALANCE
    for item in transactions:
        if item.direction is TransactionDirection.CREDIT:
            balance += item.amount
        else:
            balance -= item.amount
    return balance


def stub_statement() -> ProviderStatement:
    """The one statement the stub knows, built from the table above."""
    transactions = tuple(_transaction(index) for index in range(STUB_TRANSACTION_COUNT))
    return ProviderStatement(
        external_id=STUB_STATEMENT_EXTERNAL_ID,
        account_label=STUB_ACCOUNT_LABEL,
        period_start=STUB_PERIOD_START,
        period_end=STUB_PERIOD_END,
        currency=STUB_CURRENCY,
        opening_balance=STUB_OPENING_BALANCE,
        closing_balance=_closing_balance(transactions),
        transactions=transactions,
    )


class StubBankProvider:
    """Answers the bank protocol from memory, without a network call."""

    name = STUB_BANK_PROVIDER_NAME

    def __init__(self) -> None:
        self._statement = stub_statement()

    async def fetch_statement(self) -> ProviderStatement:
        return self._statement


def create_stub_bank_provider() -> StubBankProvider:
    """Builds the offline provider."""
    return StubBankProvider()
