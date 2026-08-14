"""Report rules: aggregation, exclusion, ranking and the cache around them."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serializers import format_datetime
from app.db.enums import DealStage
from app.modules.analytics.cache_keys import analytics_report_key
from app.modules.analytics.service import AnalyticsService
from app.modules.analytics.types import (
    AnalyticsCache,
    AnalyticsPeriod,
    DealFunnelQuery,
    OwnerPerformanceQuery,
    SalesSummaryQuery,
    StockHealthQuery,
    TopProductsQuery,
)

FROM = datetime(2026, 1, 1, tzinfo=UTC)
TO = datetime(2026, 2, 1, tzinfo=UTC)

OWNER_ONE = uuid.UUID("10000000-0000-4000-8000-000000000001")
OWNER_TWO = uuid.UUID("10000000-0000-4000-8000-000000000002")
PRODUCT_ONE = uuid.UUID("20000000-0000-4000-8000-000000000001")
PRODUCT_TWO = uuid.UUID("20000000-0000-4000-8000-000000000002")
WAREHOUSE_ONE = uuid.UUID("30000000-0000-4000-8000-000000000001")

#: Statements are rendered against the real dialect, so a test reads the SQL the
#: database would actually be sent — placeholders included.
_DIALECT: Any = postgresql.dialect()  # type: ignore[no-untyped-call]


def row(**fields: Any) -> SimpleNamespace:
    """A result row, addressed by label just as SQLAlchemy returns it."""
    return SimpleNamespace(**fields)


class FakeScalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return list(self._values)


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._rows)


class FakeSession:
    """A scripted stand-in: each call pops the next prepared answer."""

    def __init__(self, *results: list[Any]) -> None:
        self.results: list[list[Any]] = list(results)
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.results.pop(0) if self.results else [])

    @property
    def calls(self) -> int:
        return len(self.statements)

    def sql(self, index: int = -1) -> str:
        """The rendered text of one statement, without its bound values."""
        return str(self.statements[index].compile(dialect=_DIALECT))

    def params(self, index: int = -1) -> dict[str, Any]:
        return dict(self.statements[index].compile(dialect=_DIALECT).params)


class RecordingCache:
    """A cache that really stores, so a second call can be shown to hit it."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.keys: list[str] = []

    async def remember(self, key: str, ttl_seconds: int, loader: Any) -> Any:  # noqa: ARG002
        self.keys.append(key)
        if key in self.store:
            return self.store[key]
        value = await loader()
        self.store[key] = value
        return value


class BrokenCache:
    """A cache backend that is down, in the loudest possible way."""

    async def remember(self, key: str, ttl_seconds: int, loader: Any) -> Any:  # noqa: ARG002
        message = "redis down"
        raise RuntimeError(message)


def build(session: FakeSession, cache: Any | None = None) -> AnalyticsService:
    return AnalyticsService(
        cast(AsyncSession, session),
        cast(AnalyticsCache, cache) if cache is not None else RecordingCache(),
    )


class TestSalesSummary:
    async def test_maps_buckets_and_aggregates_the_totals_as_decimal_strings(self) -> None:
        session = FakeSession(
            [
                row(
                    bucket_start=datetime(2026, 1, 1, tzinfo=UTC),
                    order_count=2,
                    revenue=Decimal("100.10"),
                ),
                row(
                    bucket_start=datetime(2026, 1, 2, tzinfo=UTC),
                    order_count=3,
                    revenue="49.9",
                ),
            ]
        )
        service = build(session)

        report = await service.sales_summary(SalesSummaryQuery(FROM, TO, AnalyticsPeriod.DAY))
        body = report.model_dump(mode="json", by_alias=True)

        assert body["series"] == [
            {"bucketStart": "2026-01-01T00:00:00.000Z", "orderCount": 2, "revenue": "100.10"},
            {"bucketStart": "2026-01-02T00:00:00.000Z", "orderCount": 3, "revenue": "49.90"},
        ]
        assert body["totals"] == {
            "orderCount": 5,
            "revenue": "150.00",
            "averageOrderValue": "30.00",
        }
        assert body["period"] == "day"
        assert body["from"] == "2026-01-01T00:00:00.000Z"

    async def test_returns_zeroed_totals_for_an_empty_period(self) -> None:
        service = build(FakeSession())

        report = await service.sales_summary(SalesSummaryQuery(FROM, TO, AnalyticsPeriod.MONTH))
        body = report.model_dump(mode="json", by_alias=True)

        assert body["series"] == []
        assert body["totals"] == {
            "orderCount": 0,
            "revenue": "0.00",
            "averageOrderValue": "0.00",
        }

    async def test_binds_every_value_as_a_parameter_instead_of_concatenating_it(self) -> None:
        session = FakeSession()
        service = build(session)

        await service.sales_summary(
            SalesSummaryQuery(FROM, TO, AnalyticsPeriod.WEEK, owner_id=OWNER_ONE)
        )

        text = session.sql()
        values = list(session.params().values())
        assert str(OWNER_ONE) not in text
        assert "week" not in text
        assert "week" in values
        assert OWNER_ONE in values
        assert any(isinstance(value, datetime) for value in values)

    async def test_excludes_cancelled_and_soft_deleted_orders_in_the_query_itself(self) -> None:
        session = FakeSession()
        service = build(session)

        await service.sales_summary(SalesSummaryQuery(FROM, TO, AnalyticsPeriod.DAY))

        assert "orders.deleted_at IS NULL" in session.sql()
        assert "orders.status !=" in session.sql()
        assert "CANCELLED" in str(session.params().values())

    async def test_caches_by_the_normalised_parameters_and_reuses_the_entry(self) -> None:
        session = FakeSession()
        cache = RecordingCache()
        service = build(session, cache)

        await service.sales_summary(SalesSummaryQuery(FROM, TO, AnalyticsPeriod.DAY))
        await service.sales_summary(SalesSummaryQuery(FROM, TO, AnalyticsPeriod.DAY))
        assert session.calls == 1

        # A different period is a different report and misses the cache.
        await service.sales_summary(SalesSummaryQuery(FROM, TO, AnalyticsPeriod.MONTH))
        assert session.calls == 2

        assert (
            analytics_report_key(
                "sales-summary",
                {
                    "from": format_datetime(FROM),
                    "to": format_datetime(TO),
                    "period": "day",
                },
            )
            in cache.store
        )

    async def test_still_answers_when_the_cache_is_unavailable(self) -> None:
        session = FakeSession()
        service = build(session, BrokenCache())

        report = await service.sales_summary(SalesSummaryQuery(FROM, TO, AnalyticsPeriod.DAY))

        assert report.totals.order_count == 0
        # A cache outage must cost latency, not a duplicated database round trip.
        assert session.calls == 1

    async def test_lets_a_database_failure_surface_instead_of_retrying_it(self) -> None:
        class ExplodingSession(FakeSession):
            async def execute(self, statement: Any) -> FakeResult:
                self.statements.append(statement)
                message = "connection lost"
                raise RuntimeError(message)

        session = ExplodingSession()
        service = build(session, BrokenCache())

        with pytest.raises(RuntimeError, match="connection lost"):
            await service.sales_summary(SalesSummaryQuery(FROM, TO, AnalyticsPeriod.DAY))
        assert session.calls == 1


class TestDealFunnel:
    async def test_reports_every_stage_and_the_conversion_between_pipeline_steps(self) -> None:
        session = FakeSession(
            [
                row(stage=DealStage.LEAD, row_count=100, amount=Decimal("1000")),
                row(stage=DealStage.QUALIFIED, row_count=50, amount=Decimal("900.5")),
                row(stage=DealStage.PROPOSAL, row_count=20, amount=Decimal("800")),
                row(stage=DealStage.WON, row_count=5, amount=Decimal("400")),
                row(stage=DealStage.LOST, row_count=15, amount=Decimal("300")),
            ]
        )
        service = build(session)

        body = (await service.deal_funnel(DealFunnelQuery(FROM, TO))).model_dump(
            mode="json", by_alias=True
        )

        assert body["stages"] == [
            {"stage": "LEAD", "count": 100, "amount": "1000.00"},
            {"stage": "QUALIFIED", "count": 50, "amount": "900.50"},
            {"stage": "PROPOSAL", "count": 20, "amount": "800.00"},
            {"stage": "WON", "count": 5, "amount": "400.00"},
            {"stage": "LOST", "count": 15, "amount": "300.00"},
        ]
        # LOST is a bucket, never a step: conversion runs along the winning path.
        assert body["conversions"] == [
            {"from": "LEAD", "to": "QUALIFIED", "rate": 0.5},
            {"from": "QUALIFIED", "to": "PROPOSAL", "rate": 0.4},
            {"from": "PROPOSAL", "to": "WON", "rate": 0.25},
        ]

    async def test_reports_a_zero_rate_instead_of_dividing_by_zero(self) -> None:
        session = FakeSession([row(stage=DealStage.WON, row_count=3, amount=None)])
        service = build(session)

        body = (await service.deal_funnel(DealFunnelQuery(FROM, TO))).model_dump(
            mode="json", by_alias=True
        )

        assert body["stages"] == [
            {"stage": "LEAD", "count": 0, "amount": "0.00"},
            {"stage": "QUALIFIED", "count": 0, "amount": "0.00"},
            {"stage": "PROPOSAL", "count": 0, "amount": "0.00"},
            {"stage": "WON", "count": 3, "amount": "0.00"},
            {"stage": "LOST", "count": 0, "amount": "0.00"},
        ]
        # Every denominator here is zero, so no rate is an error or an infinity.
        assert [entry["rate"] for entry in body["conversions"]] == [0, 0, 0]

    async def test_excludes_soft_deleted_deals_and_binds_the_owner_filter(self) -> None:
        session = FakeSession()
        service = build(session)

        await service.deal_funnel(DealFunnelQuery(FROM, TO, owner_id=OWNER_ONE))

        text = session.sql()
        assert "deals.deleted_at IS NULL" in text
        assert str(OWNER_ONE) not in text
        values = list(session.params().values())
        assert OWNER_ONE in values
        assert FROM in values
        assert TO in values


class TestTopProducts:
    async def test_joins_the_catalogue_labels_onto_the_aggregated_rows(self) -> None:
        session = FakeSession(
            [
                row(product_id=PRODUCT_ONE, quantity=12, revenue=Decimal("1200.5")),
                row(product_id=PRODUCT_TWO, quantity=3, revenue=None),
            ],
            [SimpleNamespace(id=PRODUCT_ONE, sku="SKU-1", name="Widget")],
        )
        service = build(session)

        body = (await service.top_products(TopProductsQuery(FROM, TO, 5))).model_dump(
            mode="json", by_alias=True
        )

        # A product dropped from the catalogue keeps its revenue but loses its
        # label, rather than disappearing from the ranking.
        assert body["items"] == [
            {
                "productId": str(PRODUCT_ONE),
                "sku": "SKU-1",
                "name": "Widget",
                "quantity": 12,
                "revenue": "1200.50",
            },
            {
                "productId": str(PRODUCT_TWO),
                "sku": "",
                "name": "",
                "quantity": 3,
                "revenue": "0.00",
            },
        ]
        assert body["limit"] == 5

    async def test_passes_the_bounded_limit_and_the_exclusion_rules_to_the_database(self) -> None:
        session = FakeSession()
        service = build(session)

        await service.top_products(TopProductsQuery(FROM, TO, 7))

        text = session.sql(0)
        assert "orders.deleted_at IS NULL" in text
        assert "orders.status !=" in text
        assert "LIMIT" in text
        assert 7 in session.params(0).values()

    async def test_skips_the_catalogue_lookup_when_nothing_was_sold(self) -> None:
        session = FakeSession()
        service = build(session)

        report = await service.top_products(TopProductsQuery(FROM, TO, 10))

        assert report.items == []
        assert session.calls == 1


class TestOwnerPerformance:
    async def test_merges_deal_and_order_totals_per_owner(self) -> None:
        session = FakeSession(
            [
                row(owner_id=OWNER_ONE, row_count=8, amount=Decimal("4000")),
                row(owner_id=OWNER_TWO, row_count=2, amount=Decimal("500")),
            ],
            [row(owner_id=OWNER_ONE, row_count=2, amount=Decimal("1000"))],
            [
                row(owner_id=OWNER_ONE, row_count=3, amount=Decimal("300.25")),
                row(owner_id=OWNER_TWO, row_count=4, amount=Decimal("900.75")),
            ],
            [SimpleNamespace(id=OWNER_ONE, name="Ann", email="ann@example.com")],
        )
        service = build(session)

        body = (await service.owner_performance(OwnerPerformanceQuery(FROM, TO, 10))).model_dump(
            mode="json", by_alias=True
        )

        # Ordered by order revenue, so the unnamed owner comes first.
        assert body["items"] == [
            {
                "ownerId": str(OWNER_TWO),
                "name": None,
                "email": None,
                "dealCount": 2,
                "dealAmount": "500.00",
                "wonDealCount": 0,
                "wonDealAmount": "0.00",
                "winRate": 0,
                "orderCount": 4,
                "orderRevenue": "900.75",
            },
            {
                "ownerId": str(OWNER_ONE),
                "name": "Ann",
                "email": "ann@example.com",
                "dealCount": 8,
                "dealAmount": "4000.00",
                "wonDealCount": 2,
                "wonDealAmount": "1000.00",
                "winRate": 0.25,
                "orderCount": 3,
                "orderRevenue": "300.25",
            },
        ]

    async def test_applies_the_limit_after_merging(self) -> None:
        session = FakeSession(
            [
                row(owner_id=OWNER_ONE, row_count=1, amount=None),
                row(owner_id=OWNER_TWO, row_count=1, amount=None),
            ]
        )
        service = build(session)

        report = await service.owner_performance(OwnerPerformanceQuery(FROM, TO, 1))

        # Both owners were ranked; only one is published.
        assert len(report.items) == 1

    async def test_asks_for_won_deals_with_a_bound_stage_rather_than_a_second_pass(self) -> None:
        session = FakeSession()
        service = build(session)

        await service.owner_performance(OwnerPerformanceQuery(FROM, TO, 10))

        assert "deals.stage =" in session.sql(1)
        assert DealStage.WON in session.params(1).values()


class TestStockHealth:
    async def test_maps_the_rows_and_binds_the_threshold_and_limit_as_parameters(self) -> None:
        session = FakeSession(
            [
                row(
                    product_id=PRODUCT_ONE,
                    sku="SKU-1",
                    name="Widget",
                    warehouse_id=WAREHOUSE_ONE,
                    warehouse_code="CENTRAL",
                    quantity_on_hand=4,
                    quantity_reserved=3,
                    quantity_available=1,
                )
            ]
        )
        service = build(session)

        body = (await service.stock_health(StockHealthQuery(5, 20))).model_dump(
            mode="json", by_alias=True
        )

        assert body["items"] == [
            {
                "productId": str(PRODUCT_ONE),
                "sku": "SKU-1",
                "name": "Widget",
                "warehouseId": str(WAREHOUSE_ONE),
                "warehouseCode": "CENTRAL",
                "quantityOnHand": 4,
                "quantityReserved": 3,
                "quantityAvailable": 1,
            }
        ]

        values = list(session.params().values())
        assert 5 in values
        assert 20 in values
        assert "products.deleted_at IS NULL" in session.sql()

    async def test_binds_an_optional_warehouse_filter_instead_of_interpolating_it(self) -> None:
        session = FakeSession()
        service = build(session)

        await service.stock_health(StockHealthQuery(0, 10, warehouse_id=WAREHOUSE_ONE))

        assert str(WAREHOUSE_ONE) not in session.sql()
        assert WAREHOUSE_ONE in session.params().values()

    async def test_keys_the_cache_by_the_filter_so_two_warehouses_do_not_share_an_entry(
        self,
    ) -> None:
        session = FakeSession()
        cache = RecordingCache()
        service = build(session, cache)

        await service.stock_health(StockHealthQuery(5, 10))
        await service.stock_health(StockHealthQuery(5, 10, warehouse_id=WAREHOUSE_ONE))
        await service.stock_health(StockHealthQuery(5, 10))

        assert session.calls == 2
        assert len(cache.store) == 2
