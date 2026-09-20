"""The wire contract of the finance endpoints.

Most of what is asserted here is about money, and about one property in
particular: an amount is a string in both directions, and a JSON number is
refused rather than quietly accepted. That is the whole defence against a
client whose only number type cannot hold a decimal exactly, and it has to be
enforced at the boundary because by the time the value reaches any code of
ours the damage has already been done.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.enums import PaymentMatchStatus, TransactionDirection
from app.modules.finance.schemas import (
    DEFAULT_SUMMARY_DAYS,
    MAX_SUMMARY_DAYS,
    BankStatementOut,
    BankTransactionOut,
    FinanceSummaryParams,
    MatchTransactionRequest,
    StatementListParams,
    TransactionListParams,
)

NOW = datetime(2026, 1, 5, 10, 0, 0, 123_000, tzinfo=UTC)
TRANSACTION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
STATEMENT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
ORDER_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


def make_transaction_out(**overrides: object) -> BankTransactionOut:
    values: dict[str, object] = {
        "id": TRANSACTION_ID,
        "statement_id": STATEMENT_ID,
        "external_id": "stub-txn-0001",
        "booked_at": NOW,
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
    return BankTransactionOut(**(values | overrides))


# --- money on the way out --------------------------------------------------


def test_an_amount_leaves_as_a_string() -> None:
    published = make_transaction_out().model_dump(by_alias=True, mode="json")

    assert published["amount"] == "1800"
    assert isinstance(published["amount"], str)


def test_the_published_amount_keeps_its_cents_when_it_has_any() -> None:
    published = make_transaction_out(amount=Decimal("1799.99")).model_dump(
        by_alias=True, mode="json"
    )

    assert published["amount"] == "1799.99"


def test_the_balances_of_a_statement_are_strings_too() -> None:
    statement = BankStatementOut(
        id=STATEMENT_ID,
        external_id="stub-stmt-2026-01",
        account_label="Operating account",
        period_start=NOW.date(),
        period_end=NOW.date(),
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("11025.49"),
        currency="USD",
        imported_at=NOW,
        imported_by_id=None,
        created_at=NOW,
        updated_at=NOW,
    )

    published = statement.model_dump(by_alias=True, mode="json")

    assert published["openingBalance"] == "10000"
    assert published["closingBalance"] == "11025.49"
    # A period boundary is a calendar date in the column and a full timestamp on
    # the wire, so a client reads every temporal field with the same parser.
    assert published["periodStart"] == "2026-01-05T00:00:00.000Z"


def test_a_transaction_is_published_in_camel_case() -> None:
    published = make_transaction_out().model_dump(by_alias=True, mode="json")

    assert "matchStatus" in published
    assert "counterpartyName" in published
    assert "match_status" not in published


# --- money on the way in ---------------------------------------------------


@pytest.mark.parametrize("value", [19.99, 1800, Decimal("19.99")])
def test_an_amount_filter_that_is_a_number_is_refused(value: object) -> None:
    """The trap this pattern exists for.

    A client that sent ``minAmount: 19.99`` as JSON has already rounded it, and
    accepting the number would make the boundary the place the precision was
    lost rather than the place it was defended.
    """
    with pytest.raises(ValidationError):
        TransactionListParams(min_amount=value)


@pytest.mark.parametrize("value", ["19.999", "-5.00", "1e3", "", "abc", "1,000.00"])
def test_an_amount_filter_that_is_not_a_plain_decimal_is_refused(value: str) -> None:
    with pytest.raises(ValidationError):
        TransactionListParams(min_amount=value)


def test_an_amount_filter_arrives_as_the_string_it_was_sent_as() -> None:
    params = TransactionListParams(min_amount=" 19.99 ", max_amount="1800")

    assert params.min_amount == "19.99"
    assert Decimal(params.max_amount or "0") == Decimal("1800")


def test_an_upside_down_amount_range_is_refused() -> None:
    with pytest.raises(ValidationError, match="minAmount must not exceed maxAmount"):
        TransactionListParams(min_amount="100.00", max_amount="10.00")


def test_an_amount_range_of_one_value_is_allowed() -> None:
    params = TransactionListParams(min_amount="10.00", max_amount="10.00")

    assert params.min_amount == params.max_amount


# --- the ledger filters ----------------------------------------------------


def test_the_ledger_is_read_newest_booking_first_by_default() -> None:
    """A ledger is read as the account's timeline, not as the import order."""
    params = TransactionListParams()

    assert params.sort_by == "bookedAt"
    assert params.sort_order == "desc"
    assert params.page == 1
    assert params.page_size == 20


def test_an_unknown_sort_column_is_refused() -> None:
    with pytest.raises(ValidationError):
        TransactionListParams(sort_by="counterpartyName")


def test_a_booking_bound_without_a_zone_is_refused() -> None:
    # "2026-01-05T00:00:00" is a different instant in every office that sends
    # it, and reading it as UTC would answer a question nobody asked.
    with pytest.raises(ValidationError):
        TransactionListParams(booked_from="2026-01-05T00:00:00")


def test_an_upside_down_booking_window_is_refused() -> None:
    with pytest.raises(ValidationError, match="bookedFrom must not be later than bookedTo"):
        TransactionListParams(booked_from=NOW, booked_to=NOW - timedelta(days=1))


def test_a_page_larger_than_the_ceiling_is_refused() -> None:
    with pytest.raises(ValidationError):
        TransactionListParams(page_size=101)


def test_statements_are_read_by_period_by_default() -> None:
    params = StatementListParams()

    assert params.sort_by == "periodStart"
    assert params.sort_order == "desc"


# --- the write surface -----------------------------------------------------


def test_a_manual_match_states_an_order_and_a_version_and_nothing_else() -> None:
    """No amount among them: restating what the bank said is not on offer."""
    request = MatchTransactionRequest(order_id=ORDER_ID, version=3)

    assert set(request.model_dump()) == {"order_id", "version"}


def test_a_match_without_a_version_is_refused() -> None:
    # The version is how the client says which state of the record it decided
    # about; without it there is no race to lose.
    with pytest.raises(ValidationError):
        MatchTransactionRequest(order_id=ORDER_ID)


def test_a_version_below_one_is_refused() -> None:
    with pytest.raises(ValidationError):
        MatchTransactionRequest(order_id=ORDER_ID, version=0)


# --- the summary window ----------------------------------------------------


def test_a_summary_with_no_bounds_covers_the_default_window() -> None:
    params = FinanceSummaryParams()

    assert params.range_to - params.range_from == timedelta(days=DEFAULT_SUMMARY_DAYS)


def test_a_summary_bound_arrives_under_its_published_name() -> None:
    params = FinanceSummaryParams.model_validate({"from": NOW, "to": NOW + timedelta(days=1)})

    assert params.range_from == NOW


def test_a_summary_bound_without_a_zone_is_read_as_utc() -> None:
    params = FinanceSummaryParams.model_validate(
        {"from": "2026-01-01T00:00:00", "to": "2026-01-31T00:00:00"}
    )

    assert params.range_from == datetime(2026, 1, 1, tzinfo=UTC)


def test_an_upside_down_summary_window_is_refused() -> None:
    with pytest.raises(ValidationError, match="from must be earlier than to"):
        FinanceSummaryParams.model_validate({"from": NOW, "to": NOW})


def test_a_summary_window_wider_than_the_ceiling_is_refused() -> None:
    # One request must not be able to walk years of ledger.
    with pytest.raises(ValidationError, match="must not exceed"):
        FinanceSummaryParams.model_validate(
            {"from": NOW, "to": NOW + timedelta(days=MAX_SUMMARY_DAYS + 1)}
        )
