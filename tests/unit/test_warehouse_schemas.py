"""What the warehouse endpoints accept, and what they refuse outright."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.modules.warehouse.schemas import (
    AdjustStockRequest,
    CreateWarehouseRequest,
    IssueStockRequest,
    MovementListParams,
    ReserveStockRequest,
    StockLevelOut,
    UpdateWarehouseRequest,
)

NOW = datetime(2026, 8, 12, 15, 23, 45, 123_000, tzinfo=UTC)
WAREHOUSE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
PRODUCT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
ORDER_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


def stock_target() -> dict[str, str]:
    return {"warehouseId": str(WAREHOUSE_ID), "productId": str(PRODUCT_ID)}


def test_a_warehouse_code_is_folded_to_upper_case() -> None:
    payload = CreateWarehouseRequest.model_validate({"code": " main-01 ", "name": "Main"})

    assert payload.code == "MAIN-01"


@pytest.mark.parametrize("code", ["-main", "ma in", "m", "головний"])
def test_a_code_outside_the_allowed_alphabet_is_rejected(code: str) -> None:
    with pytest.raises(ValidationError):
        CreateWarehouseRequest.model_validate({"code": code, "name": "Main"})


def test_a_patch_with_no_fields_is_rejected() -> None:
    with pytest.raises(ValidationError):
        UpdateWarehouseRequest()


def test_a_patch_distinguishes_an_absent_field_from_a_given_one() -> None:
    payload = UpdateWarehouseRequest.model_validate({"isActive": False})

    assert payload.model_fields_set == {"is_active"}
    assert payload.name is None


def test_an_issue_against_a_reservation_must_name_the_reservation() -> None:
    with pytest.raises(ValidationError):
        IssueStockRequest.model_validate({**stock_target(), "quantity": 2, "fromReservation": True})


def test_an_issue_against_a_reservation_is_accepted_with_a_reference() -> None:
    payload = IssueStockRequest.model_validate(
        {
            **stock_target(),
            "quantity": 2,
            "fromReservation": True,
            "referenceType": "order",
            "referenceId": str(ORDER_ID),
        }
    )

    assert payload.from_reservation is True
    assert payload.reference_id == ORDER_ID


def test_a_plain_issue_needs_no_reference() -> None:
    payload = IssueStockRequest.model_validate({**stock_target(), "quantity": 2})

    assert payload.from_reservation is False
    assert payload.reference_type is None


@pytest.mark.parametrize("quantity", [0, -1])
def test_a_movement_of_zero_or_fewer_units_is_rejected(quantity: int) -> None:
    with pytest.raises(ValidationError):
        IssueStockRequest.model_validate({**stock_target(), "quantity": quantity})


def test_a_reservation_without_a_reference_is_rejected() -> None:
    # A reservation is always held on behalf of something.
    with pytest.raises(ValidationError):
        ReserveStockRequest.model_validate({**stock_target(), "quantity": 2})


def test_an_adjustment_of_zero_records_nothing_and_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AdjustStockRequest.model_validate({**stock_target(), "delta": 0, "note": "recount"})


def test_an_adjustment_without_a_reason_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AdjustStockRequest.model_validate({**stock_target(), "delta": -1})


def test_an_adjustment_may_be_negative() -> None:
    payload = AdjustStockRequest.model_validate({**stock_target(), "delta": -3, "note": "breakage"})

    assert payload.delta == -3


def test_a_movement_window_may_not_end_before_it_starts() -> None:
    with pytest.raises(ValidationError):
        MovementListParams.model_validate(
            {"createdFrom": "2026-08-12T10:00:00Z", "createdTo": "2026-08-11T10:00:00Z"}
        )


def test_an_unknown_query_field_is_not_silently_dropped() -> None:
    params = MovementListParams.model_validate({"page": 3, "pageSize": 5})

    assert (params.page, params.page_size) == (3, 5)


def test_the_published_level_carries_the_derived_availability() -> None:
    level = StockLevelOut(
        id=uuid.uuid4(),
        warehouse_id=WAREHOUSE_ID,
        product_id=PRODUCT_ID,
        quantity_on_hand=10,
        quantity_reserved=4,
        version=3,
        created_at=NOW,
        updated_at=NOW,
    )

    payload = level.model_dump(by_alias=True)

    assert payload["quantityAvailable"] == 6
    assert payload["quantityOnHand"] == 10
