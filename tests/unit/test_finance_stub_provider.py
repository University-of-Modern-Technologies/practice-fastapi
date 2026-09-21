"""The bank fixture, pinned.

What an import files shows up through the API a moment later, so this table is
shared data rather than an implementation detail: the identifiers, the dates,
the amounts and the balances all have to be the same on both backends. Asserted
here line by line, because a fixture that drifts is a cross-backend failure
that surfaces as a mysteriously different total somewhere else entirely.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.db.enums import TransactionDirection
from app.modules.finance.stub_provider import (
    STUB_OPENING_BALANCE,
    STUB_STATEMENT_EXTERNAL_ID,
    STUB_TRANSACTION_COUNT,
    StubBankProvider,
    stub_statement,
)

FIRST_BOOKING = datetime(2026, 3, 2, 10, 0, tzinfo=UTC)
BOOKING_STEP = timedelta(days=2)


def test_the_statement_header_is_the_one_the_contract_names() -> None:
    statement = stub_statement()

    assert statement.external_id == STUB_STATEMENT_EXTERNAL_ID == "stub-stmt-2026-03"
    assert statement.account_label == "Operating account"
    assert statement.period_start == date(2026, 3, 1)
    assert statement.period_end == date(2026, 3, 31)
    assert statement.currency == "USD"
    assert statement.opening_balance == Decimal("10000.00")


def test_the_statement_carries_twelve_lines_numbered_from_one() -> None:
    statement = stub_statement()

    assert STUB_TRANSACTION_COUNT == 12
    assert [item.external_id for item in statement.transactions] == [
        f"stub-txn-2026-03-{index:04d}" for index in range(1, 13)
    ]


def test_the_lines_are_booked_two_days_apart_from_a_fixed_anchor() -> None:
    statement = stub_statement()

    assert [item.booked_at for item in statement.transactions] == [
        FIRST_BOOKING + BOOKING_STEP * index for index in range(STUB_TRANSACTION_COUNT)
    ]


def test_the_closing_balance_is_the_opening_balance_plus_the_flow() -> None:
    """Derived rather than quoted, so editing a line cannot leave it stale."""
    statement = stub_statement()

    flow = sum(
        (
            item.amount if item.direction is TransactionDirection.CREDIT else -item.amount
            for item in statement.transactions
        ),
        Decimal(0),
    )

    assert statement.closing_balance == STUB_OPENING_BALANCE + flow


def test_the_money_going_out_is_the_last_three_lines_but_one() -> None:
    # Outgoing money is in the fixture so that the rule has something it must
    # decline to reconcile, which is a branch nothing else would reach.
    statement = stub_statement()
    debits = [
        item.external_id
        for item in statement.transactions
        if item.direction is TransactionDirection.DEBIT
    ]

    assert debits == [
        "stub-txn-2026-03-0009",
        "stub-txn-2026-03-0010",
        "stub-txn-2026-03-0011",
    ]


def test_two_lines_are_deliberately_indistinguishable() -> None:
    """Without these the ``SUGGESTED`` branch is unreachable from the fixture."""
    statement = stub_statement()
    seventh, eighth = statement.transactions[6], statement.transactions[7]

    assert seventh.amount == eighth.amount == Decimal("990.00")
    assert seventh.counterparty_name == eighth.counterparty_name
    assert "ORD" not in seventh.reference.upper()
    assert seventh.external_id != eighth.external_id


def test_one_line_is_a_cent_short_of_the_order_it_names() -> None:
    fourth = stub_statement().transactions[3]

    assert fourth.amount == Decimal("1249.99")
    assert "ord-2026-0006" in fourth.reference.casefold()


def test_one_line_names_no_order_and_only_the_payer() -> None:
    fifth = stub_statement().transactions[4]

    assert "ORD" not in fifth.reference.upper()
    assert fifth.counterparty_name == "Jordan Blue"


def test_one_line_fits_nothing_at_all() -> None:
    # The honest majority of a real feed, and the state the module has to be
    # comfortable leaving a payment in.
    sixth = stub_statement().transactions[5]

    assert sixth.amount == Decimal("66.00")
    assert sixth.counterparty_account is None


def test_every_line_is_in_the_currency_of_the_statement() -> None:
    statement = stub_statement()

    assert {item.currency for item in statement.transactions} == {statement.currency}


def test_no_amount_is_ever_a_float() -> None:
    """The one property of this fixture that a language could quietly break."""
    statement = stub_statement()

    assert isinstance(statement.opening_balance, Decimal)
    assert isinstance(statement.closing_balance, Decimal)
    for item in statement.transactions:
        assert isinstance(item.amount, Decimal)


async def test_the_provider_answers_the_same_statement_every_time() -> None:
    """Generated from constants rather than from the clock.

    This is what makes a second import file nothing rather than merely be
    likely to: the identifiers are the same on every run of the process.
    """
    provider = StubBankProvider()

    first = await provider.fetch_statement()
    second = await provider.fetch_statement()

    assert first == second == stub_statement()
    assert provider.name == "stub"
