"""Report query normalisation: defaults, bounds and clamping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.serializers import format_datetime
from app.modules.analytics.kyiv_time import default_kyiv_window_to
from app.modules.analytics.schemas import (
    DEFAULT_RANGE_FROM,
    MAX_LIMIT,
    MAX_RANGE_DAYS,
    DealFunnelParams,
    SalesSummaryParams,
    StockHealthParams,
    TopProductsParams,
)
from app.modules.analytics.types import AnalyticsPeriod

OWNER_ID = "10000000-0000-4000-8000-000000000001"


def parses(model: Any, query: dict[str, Any]) -> bool:
    """Whether a query string is accepted at all."""
    try:
        model.model_validate(query)
    except ValidationError:
        return False
    return True


class TestDateRange:
    def test_defaults_the_range_to_a_fixed_start_and_the_end_of_today(self) -> None:
        """A window measured back from the clock would lose the demonstration data.

        The start stays where the data begins, and the end covers today, so a
        record entered this morning is in the report asked for this afternoon.
        """
        params = SalesSummaryParams()
        assert params.range_from == DEFAULT_RANGE_FROM
        assert params.range_to == default_kyiv_window_to()
        assert params.range_to > datetime.now(UTC)
        assert params.period is AnalyticsPeriod.DAY

    def test_fills_only_the_bound_the_caller_left_out(self) -> None:
        params = SalesSummaryParams.model_validate({"from": "2026-01-01T00:00:00Z"})

        assert format_datetime(params.range_from) == "2026-01-01T00:00:00.000Z"
        assert params.range_to == default_kyiv_window_to()

    def test_normalises_dates_to_utc_and_stays_idempotent_on_a_second_parse(self) -> None:
        first = SalesSummaryParams.model_validate(
            {"from": "2026-01-01", "to": "2026-02-01", "period": "week"}
        )
        # A bare date is the day as Kyiv lives it: its midnight, in UTC.
        assert format_datetime(first.range_from) == "2025-12-31T22:00:00.000Z"
        assert format_datetime(first.range_to) == "2026-01-31T22:00:00.000Z"

        # The published form of a range is itself a valid range, which is what
        # lets a cache key be built from it and re-read later.
        second = SalesSummaryParams.model_validate(
            {
                "from": format_datetime(first.range_from),
                "to": format_datetime(first.range_to),
                "period": "week",
            }
        )
        assert second.to_query() == first.to_query()

    def test_reads_a_zoneless_bound_on_the_kyiv_clock_rather_than_as_local_time(self) -> None:
        params = DealFunnelParams.model_validate({"from": "2026-01-01T00:00:00"})
        assert params.range_from == datetime(2025, 12, 31, 22, tzinfo=UTC)

    def test_cuts_a_day_at_kyiv_midnight_summer_time_included(self) -> None:
        """An order placed at 00:30 in Kyiv belongs to the day Kyiv's clock showed."""
        winter = SalesSummaryParams.model_validate({"from": "2026-03-11", "to": "2026-03-12"})
        half_past_midnight_in_winter = datetime(2026, 3, 10, 22, 30, tzinfo=UTC)
        assert winter.range_from == datetime(2026, 3, 10, 22, tzinfo=UTC)
        assert winter.range_to == datetime(2026, 3, 11, 22, tzinfo=UTC)
        assert winter.range_from <= half_past_midnight_in_winter < winter.range_to

        summer = SalesSummaryParams.model_validate({"from": "2026-07-11", "to": "2026-07-12"})
        half_past_midnight_in_summer = datetime(2026, 7, 10, 21, 30, tzinfo=UTC)
        assert summer.range_from == datetime(2026, 7, 10, 21, tzinfo=UTC)
        assert summer.range_to == datetime(2026, 7, 11, 21, tzinfo=UTC)
        assert summer.range_from <= half_past_midnight_in_summer < summer.range_to

        # The day before ends where this one starts, so the order is not in it.
        day_before = SalesSummaryParams.model_validate({"from": "2026-03-10", "to": "2026-03-11"})
        assert half_past_midnight_in_winter >= day_before.range_to

    def test_gives_the_days_of_a_clock_change_their_real_length(self) -> None:
        """The day the clocks go forward is 23 hours long, the day they go back 25."""
        spring = SalesSummaryParams.model_validate({"from": "2026-03-29", "to": "2026-03-30"})
        assert spring.range_from == datetime(2026, 3, 28, 22, tzinfo=UTC)
        assert spring.range_to == datetime(2026, 3, 29, 21, tzinfo=UTC)

        autumn = SalesSummaryParams.model_validate({"from": "2026-10-25", "to": "2026-10-26"})
        assert autumn.range_from == datetime(2026, 10, 24, 21, tzinfo=UTC)
        assert autumn.range_to == datetime(2026, 10, 25, 22, tzinfo=UTC)

    def test_rejects_an_inverted_date_range(self) -> None:
        assert not parses(SalesSummaryParams, {"from": "2026-02-01", "to": "2026-01-01"})

    def test_rejects_an_empty_date_range(self) -> None:
        assert not parses(DealFunnelParams, {"from": "2026-01-01", "to": "2026-01-01"})

    def test_rejects_an_excessively_wide_date_range(self) -> None:
        start = datetime(2020, 1, 1, tzinfo=UTC)
        just_inside = start + timedelta(days=MAX_RANGE_DAYS)
        just_outside = start + timedelta(days=MAX_RANGE_DAYS + 1)

        assert parses(
            DealFunnelParams,
            {"from": format_datetime(start), "to": format_datetime(just_inside)},
        )
        assert not parses(
            DealFunnelParams,
            {"from": format_datetime(start), "to": format_datetime(just_outside)},
        )

    def test_rejects_an_unparsable_date(self) -> None:
        assert not parses(SalesSummaryParams, {"from": "yesterday"})


class TestReportParameters:
    def test_restricts_the_period_to_the_supported_buckets(self) -> None:
        assert parses(SalesSummaryParams, {"period": "month"})
        assert not parses(SalesSummaryParams, {"period": "hour"})

    def test_clamps_the_limit_to_the_ceiling_and_coerces_a_query_string(self) -> None:
        assert TopProductsParams.model_validate({"limit": "5"}).limit == 5
        # Asking for everything yields the largest page, not an error.
        assert TopProductsParams.model_validate({"limit": "5000"}).limit == MAX_LIMIT
        assert TopProductsParams().limit == 10
        assert not parses(TopProductsParams, {"limit": "0"})
        assert not parses(TopProductsParams, {"limit": "2.5"})

    def test_defaults_and_bounds_the_stock_threshold(self) -> None:
        assert StockHealthParams().threshold == 5
        # Zero is meaningful: it asks for what is already out of stock.
        assert StockHealthParams.model_validate({"threshold": "0"}).threshold == 0
        assert not parses(StockHealthParams, {"threshold": "-1"})
        assert StockHealthParams.model_validate({"limit": "900"}).limit == MAX_LIMIT

    @pytest.mark.parametrize("model", [DealFunnelParams, SalesSummaryParams])
    def test_rejects_an_owner_filter_that_is_not_an_identifier(self, model: Any) -> None:
        assert not parses(model, {"ownerId": "not-a-uuid"})
        assert parses(model, {"ownerId": OWNER_ID})

    def test_rejects_a_warehouse_filter_that_is_not_an_identifier(self) -> None:
        assert not parses(StockHealthParams, {"warehouseId": "not-a-uuid"})
        assert parses(StockHealthParams, {"warehouseId": OWNER_ID})

    def test_hands_the_service_a_fully_resolved_query(self) -> None:
        query = SalesSummaryParams.model_validate(
            {"from": "2026-01-01", "to": "2026-02-01", "period": "month", "ownerId": OWNER_ID}
        ).to_query()

        assert query.from_ == datetime(2025, 12, 31, 22, tzinfo=UTC)
        assert query.to == datetime(2026, 1, 31, 22, tzinfo=UTC)
        assert query.period is AnalyticsPeriod.MONTH
        assert str(query.owner_id) == OWNER_ID

    def test_truncates_bounds_to_the_stored_resolution(self) -> None:
        """Anything finer than a millisecond cannot change which rows match.

        Keeping it would make two requests that share a cache key produce two
        different result sets — one key holding two answers.
        """
        params = SalesSummaryParams.model_validate(
            {"from": "2026-01-01T00:00:00.999999Z", "to": "2026-02-01T00:00:00.123456Z"}
        )

        assert params.range_from == datetime(2026, 1, 1, 0, 0, 0, 999_000, tzinfo=UTC)
        assert params.range_to == datetime(2026, 2, 1, 0, 0, 0, 123_000, tzinfo=UTC)

    def test_the_default_upper_bound_is_truncated_too(self) -> None:
        params = SalesSummaryParams()

        assert params.range_to.microsecond % 1_000 == 0
        assert params.range_from.microsecond % 1_000 == 0


class TestDateBoundGrammar:
    def test_reads_a_date_time_without_a_zone_on_the_kyiv_clock(self) -> None:
        """A missing zone is not the server's, as in the sibling backend.

        Since the day boundaries moved to Kyiv it is Kyiv's clock, so a bare
        date and the same date at midnight name one instant.
        """
        params = SalesSummaryParams.model_validate(
            {"from": "2026-01-01T10:30", "to": "2026-01-02T00:00:00.5"}
        )

        assert format_datetime(params.range_from) == "2026-01-01T08:30:00.000Z"
        assert format_datetime(params.range_to) == "2026-01-01T22:00:00.500Z"

    def test_honours_an_offset_and_truncates_below_the_millisecond(self) -> None:
        params = SalesSummaryParams.model_validate(
            {"from": "2026-01-01T02:00:00.123987+02:00", "to": "2026-01-02T00:00:00Z"}
        )

        assert format_datetime(params.range_from) == "2026-01-01T00:00:00.123Z"

    @pytest.mark.parametrize(
        "junk",
        [
            "1",
            "2026",
            "2026-02-31",
            "2026-01-01 10:00",
            "2026-01-01T10:00:00+0200",
            "2026-01-01T24:00",
            " 2026-01-01",
            "Jan 1 2026",
        ],
    )
    def test_refuses_anything_that_is_not_an_iso_8601_date_or_timestamp(self, junk: str) -> None:
        """The parser underneath would read "1" as a Unix timestamp."""
        assert not parses(SalesSummaryParams, {"from": junk})
