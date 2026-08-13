"""The arithmetic of stock, tested as the pure functions it is.

Sufficiency is decided before anything is written, so it can be checked without
a database: a plan plus the quantities currently on the shelf is all the input
the rule needs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from app.core.errors import AppError
from app.db.enums import StockMovementType
from app.modules.warehouse.schemas import (
    AdjustStockRequest,
    IssueStockRequest,
    ReceiveStockRequest,
    ReserveStockRequest,
)
from app.modules.warehouse.service import (
    adjust_plan,
    issue_plan,
    next_quantities,
    receive_plan,
    release_plan,
    reserve_plan,
)
from app.modules.warehouse.types import (
    INSUFFICIENT_RESERVATION,
    INSUFFICIENT_STOCK,
    INVALID_STOCK_ADJUSTMENT,
    STOCK_ADJUSTMENT_NOTE_REQUIRED,
)

WAREHOUSE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
PRODUCT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
ORDER_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


def target() -> dict[str, str]:
    return {"warehouseId": str(WAREHOUSE_ID), "productId": str(PRODUCT_ID)}


def reservation(quantity: int = 2) -> ReserveStockRequest:
    return ReserveStockRequest.model_validate(
        {
            **target(),
            "quantity": quantity,
            "referenceType": "order",
            "referenceId": str(ORDER_ID),
        }
    )


@dataclass(frozen=True, slots=True)
class ForeignRequest:
    """A stock request as another module would shape it.

    Nothing here inherits from the warehouse schemas; it satisfies the port by
    its fields alone, which is exactly how the orders module reaches this code.
    """

    warehouse_id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    reference_type: str
    reference_id: uuid.UUID
    from_reservation: bool = False


def test_receiving_adds_to_the_shelf_and_leaves_the_reservation_alone() -> None:
    plan = receive_plan(ReceiveStockRequest.model_validate({**target(), "quantity": 5}))

    assert plan.movement_type is StockMovementType.RECEIPT
    assert (plan.on_hand_delta, plan.reserved_delta) == (5, 0)


def test_reserving_promises_units_without_removing_them() -> None:
    plan = reserve_plan(reservation(2))

    assert plan.movement_type is StockMovementType.RESERVATION
    assert (plan.on_hand_delta, plan.reserved_delta) == (0, 2)


def test_releasing_gives_promised_units_back_without_touching_the_shelf() -> None:
    plan = release_plan(reservation(2))

    assert (plan.on_hand_delta, plan.reserved_delta) == (0, -2)


def test_a_plain_issue_only_removes_units_from_the_shelf() -> None:
    plan = issue_plan(IssueStockRequest.model_validate({**target(), "quantity": 4}))

    assert (plan.on_hand_delta, plan.reserved_delta) == (-4, 0)


def test_an_issue_against_a_reservation_consumes_the_reservation_too() -> None:
    plan = issue_plan(
        IssueStockRequest.model_validate(
            {
                **target(),
                "quantity": 4,
                "fromReservation": True,
                "referenceType": "order",
                "referenceId": str(ORDER_ID),
            }
        )
    )

    # Both counters move: otherwise the row would keep units reserved that are
    # no longer on the shelf.
    assert (plan.on_hand_delta, plan.reserved_delta) == (-4, -4)


def test_a_plan_is_built_from_a_structure_the_module_has_never_seen() -> None:
    plan = reserve_plan(
        ForeignRequest(
            warehouse_id=WAREHOUSE_ID,
            product_id=PRODUCT_ID,
            quantity=3,
            reference_type="order",
            reference_id=ORDER_ID,
        )
    )

    assert (plan.reserved_delta, plan.reference_type, plan.note) == (3, "order", None)


def test_an_adjustment_records_a_positive_quantity_for_a_negative_delta() -> None:
    plan = adjust_plan(
        AdjustStockRequest.model_validate({**target(), "delta": -3, "note": " breakage "})
    )

    assert plan.movement_type is StockMovementType.ADJUSTMENT
    assert (plan.quantity, plan.on_hand_delta) == (3, -3)
    assert plan.note == "breakage"


def test_an_adjustment_of_zero_is_refused_before_any_row_is_read() -> None:
    request = AdjustStockRequest.model_construct(
        warehouse_id=WAREHOUSE_ID,
        product_id=PRODUCT_ID,
        delta=0,
        note="recount",
        reference_type=None,
        reference_id=None,
    )

    with pytest.raises(AppError) as error:
        adjust_plan(request)

    assert (error.value.status_code, error.value.code) == (400, INVALID_STOCK_ADJUSTMENT)


def test_an_adjustment_without_a_reason_is_refused() -> None:
    request = AdjustStockRequest.model_construct(
        warehouse_id=WAREHOUSE_ID,
        product_id=PRODUCT_ID,
        delta=-2,
        note="   ",
        reference_type=None,
        reference_id=None,
    )

    with pytest.raises(AppError) as error:
        adjust_plan(request)

    assert (error.value.status_code, error.value.code) == (400, STOCK_ADJUSTMENT_NOTE_REQUIRED)


def test_a_reservation_is_measured_against_available_stock_not_the_shelf() -> None:
    # Ten on the shelf, four already promised: six may still be promised.
    assert next_quantities(10, 4, reserve_plan(reservation(6))) == (10, 10)


def test_reserving_more_than_is_available_is_an_oversell() -> None:
    with pytest.raises(AppError) as error:
        next_quantities(10, 4, reserve_plan(reservation(7)))

    assert (error.value.status_code, error.value.code) == (409, INSUFFICIENT_STOCK)


def test_issuing_more_than_is_on_the_shelf_is_an_oversell() -> None:
    plan = issue_plan(IssueStockRequest.model_validate({**target(), "quantity": 11}))

    with pytest.raises(AppError) as error:
        next_quantities(10, 0, plan)

    assert error.value.code == INSUFFICIENT_STOCK


def test_issuing_unreserved_units_may_not_leave_reservations_uncovered() -> None:
    # Ten on the shelf, all ten promised: issuing outside the reservation would
    # leave promises that nothing backs.
    plan = issue_plan(IssueStockRequest.model_validate({**target(), "quantity": 1}))

    with pytest.raises(AppError) as error:
        next_quantities(10, 10, plan)

    assert error.value.code == INSUFFICIENT_STOCK


def test_releasing_more_than_was_reserved_is_a_reservation_failure() -> None:
    with pytest.raises(AppError) as error:
        next_quantities(10, 4, release_plan(reservation(5)))

    assert (error.value.status_code, error.value.code) == (409, INSUFFICIENT_RESERVATION)


def test_an_issue_against_a_reservation_larger_than_the_hold_is_refused() -> None:
    plan = issue_plan(
        IssueStockRequest.model_validate(
            {
                **target(),
                "quantity": 5,
                "fromReservation": True,
                "referenceType": "order",
                "referenceId": str(ORDER_ID),
            }
        )
    )

    with pytest.raises(AppError) as error:
        next_quantities(10, 4, plan)

    assert error.value.code == INSUFFICIENT_RESERVATION


def test_an_operation_against_a_pair_that_was_never_stocked_starts_at_zero() -> None:
    assert next_quantities(
        0, 0, receive_plan(ReceiveStockRequest.model_validate({**target(), "quantity": 5}))
    ) == (5, 0)

    with pytest.raises(AppError) as error:
        next_quantities(0, 0, reserve_plan(reservation(1)))

    assert error.value.code == INSUFFICIENT_STOCK


def test_neither_counter_can_be_driven_below_zero() -> None:
    plan = adjust_plan(
        AdjustStockRequest.model_validate({**target(), "delta": -11, "note": "recount"})
    )

    with pytest.raises(AppError) as error:
        next_quantities(10, 0, plan)

    assert error.value.code == INSUFFICIENT_STOCK
