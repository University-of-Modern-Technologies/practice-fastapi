"""The wire contract of the deals endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.db.enums import DealStage
from app.modules.deals.schemas import (
    CreateDealRequest,
    DealListParams,
    DealOut,
    TransitionDealRequest,
    UpdateDealRequest,
)

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)


def make_deal_out(**overrides: Any) -> DealOut:
    payload: dict[str, Any] = {
        "id": uuid.uuid4(),
        "owner_id": uuid.uuid4(),
        "contact_id": None,
        "title": "Opportunity",
        "stage": DealStage.LEAD,
        "amount": Decimal("12.5"),
        "currency": "USD",
        "probability": 10,
        "version": 1,
        "expected_close_date": date(2026, 9, 1),
        "closed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return DealOut(**(payload | overrides))


def test_an_amount_travels_as_a_string_with_a_fixed_scale() -> None:
    payload = make_deal_out().model_dump(by_alias=True)

    # Shortest exact form: a stored amount reaches the client without the
    # padding the column carries, exactly as the sibling backend renders it.
    assert payload["amount"] == "12.5"
    # A date-only column still travels as a full timestamp: the client parses
    # every temporal field the same way.
    assert payload["expectedCloseDate"] == "2026-09-01T00:00:00.000Z"
    assert payload["createdAt"] == "2026-08-12T15:23:45.123Z"


def test_an_amount_is_read_from_a_string_without_touching_a_float() -> None:
    request = CreateDealRequest.model_validate({"title": "Opportunity", "amount": "1234.50"})

    assert request.amount == Decimal("1234.50")


@pytest.mark.parametrize("amount", ["12.345", "-5", "", "1e3", "abc", 12.5, 1250])
def test_an_amount_the_column_cannot_hold_is_rejected(amount: object) -> None:
    with pytest.raises(ValidationError):
        CreateDealRequest.model_validate({"title": "Opportunity", "amount": amount})


def test_a_currency_code_is_folded_to_upper_case() -> None:
    request = CreateDealRequest.model_validate(
        {"title": "Opportunity", "amount": "1.00", "currency": " usd "}
    )

    assert request.currency == "USD"


@pytest.mark.parametrize("currency", ["us", "dollars", "12$"])
def test_a_currency_that_is_not_a_three_letter_code_is_rejected(currency: str) -> None:
    with pytest.raises(ValidationError):
        CreateDealRequest.model_validate(
            {"title": "Opportunity", "amount": "1.00", "currency": currency}
        )


@pytest.mark.parametrize("stage", ["QUALIFIED", "WON", "LOST", "PROPOSAL"])
def test_a_deal_can_only_be_created_at_the_start_of_the_pipeline(stage: str) -> None:
    with pytest.raises(ValidationError):
        CreateDealRequest.model_validate({"title": "Opportunity", "amount": "1.00", "stage": stage})

    accepted = CreateDealRequest.model_validate(
        {"title": "Opportunity", "amount": "1.00", "stage": "LEAD"}
    )
    assert accepted.stage is DealStage.LEAD


def test_an_update_body_has_no_stage_field_at_all() -> None:
    # The whole state machine would be decorative if an ordinary edit could
    # advance the pipeline, so the field is refused rather than ignored.
    assert "stage" not in UpdateDealRequest.model_fields

    with pytest.raises(ValidationError):
        UpdateDealRequest.model_validate({"version": 1, "stage": "WON"})


def test_an_update_that_changes_nothing_is_rejected() -> None:
    with pytest.raises(ValidationError):
        UpdateDealRequest.model_validate({"version": 1})


def test_an_update_distinguishes_an_absent_field_from_an_explicit_null() -> None:
    absent = UpdateDealRequest.model_validate({"version": 1, "title": "Renamed"})
    cleared = UpdateDealRequest.model_validate({"version": 1, "contactId": None})

    assert "contact_id" not in absent.model_fields_set
    assert "contact_id" in cleared.model_fields_set
    assert cleared.contact_id is None


def test_an_update_carries_a_version_the_client_must_have_read() -> None:
    with pytest.raises(ValidationError):
        UpdateDealRequest.model_validate({"version": 0, "title": "Renamed"})


def test_a_transition_names_the_target_stage_and_the_version() -> None:
    request = TransitionDealRequest.model_validate({"version": 3, "stage": "WON"})

    assert request.stage is DealStage.WON
    assert request.version == 3
    assert request.probability is None

    with pytest.raises(ValidationError):
        TransitionDealRequest.model_validate({"stage": "WON"})


def test_list_parameters_are_read_under_the_names_the_client_uses() -> None:
    params = DealListParams.model_validate(
        {
            "page": 2,
            "pageSize": 50,
            "minAmount": "10.00",
            "maxAmount": "20.00",
            "minProbability": 10,
            "maxProbability": 90,
            "expectedCloseFrom": "2026-01-01",
            "sortBy": "amount",
            "sortOrder": "asc",
        }
    )

    assert params.page_size == 50
    assert params.min_amount == Decimal("10.00")
    assert params.expected_close_from == date(2026, 1, 1)
    assert params.sort_by == "amount"


def test_list_parameters_default_to_the_newest_first() -> None:
    params = DealListParams()

    assert (params.page, params.page_size) == (1, 20)
    assert (params.sort_by, params.sort_order) == ("createdAt", "desc")


@pytest.mark.parametrize(
    "query",
    [
        {"minAmount": "20.00", "maxAmount": "10.00"},
        {"minProbability": 90, "maxProbability": 10},
    ],
)
def test_an_inverted_range_is_rejected(query: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DealListParams.model_validate(query)


def test_an_unknown_query_parameter_is_ignored_rather_than_refused() -> None:
    # A query string collects keys nobody asked for; only a request body is
    # strict about what it accepts.
    params = DealListParams.model_validate({"orderBy": "amount", "_": "1754999999"})

    assert params.sort_by == "createdAt"
