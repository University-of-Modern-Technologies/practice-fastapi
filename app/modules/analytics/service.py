"""Read-only reporting over the operational tables.

This module never writes: there is no mutating method here and no route that
could reach one.

Two exclusion rules apply to every report and are repeated at each query so the
behaviour is discoverable from the query itself:

1. soft-deleted rows (``deleted_at IS NOT NULL``) are invisible;
2. cancelled orders never contribute to revenue or to product rankings.

An order is dated by ``placed_at`` and falls back to ``created_at`` while it is
still a draft, so a range filter always has a timestamp to work with.

Every value that comes from the caller — a date bound, a bucket width, a limit,
an owner id — reaches the database as a bound parameter. Nothing here builds SQL
by concatenating text.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serializers import format_datetime
from app.db.enums import DealStage, OrderStatus
from app.db.models.deal import Deal
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.db.models.user import User
from app.db.models.warehouse import StockLevel, Warehouse
from app.modules.analytics.cache_keys import analytics_report_key
from app.modules.analytics.decimal import (
    DecimalInput,
    average_decimal,
    format_decimal,
    ratio,
    sum_decimals,
    to_scaled_integer,
)
from app.modules.analytics.schemas import (
    DealFunnelConversion,
    DealFunnelReport,
    DealFunnelStage,
    OwnerPerformanceReport,
    OwnerPerformanceRow,
    SalesSummaryBucket,
    SalesSummaryReport,
    SalesSummaryTotals,
    StockHealthReport,
    StockHealthRow,
    TopProductRow,
    TopProductsReport,
)
from app.modules.analytics.types import (
    DEAL_FUNNEL_REPORT,
    DEFAULT_ANALYTICS_TTL_SECONDS,
    FUNNEL_PIPELINE,
    OWNER_PERFORMANCE_REPORT,
    SALES_SUMMARY_REPORT,
    STOCK_HEALTH_REPORT,
    TOP_PRODUCTS_REPORT,
    AnalyticsCache,
    DealFunnelQuery,
    NoopAnalyticsCache,
    OwnerPerformanceQuery,
    SalesSummaryQuery,
    StockHealthQuery,
    TopProductsQuery,
)

__all__ = [
    "AnalyticsService",
    "deal_funnel_statement",
    "order_date_window",
    "sales_summary_statement",
    "stock_health_statement",
    "top_products_statement",
]


@dataclass(frozen=True, slots=True)
class _Aggregate:
    """One ``COUNT``/``SUM`` pair, so an absent group reads like an empty one."""

    count: int | None = None
    amount: DecimalInput = None

    @property
    def count_value(self) -> int:
        """The count as a plain integer; an absent group counts as zero."""
        return int(self.count or 0)


#: Stand-in for a group the query returned no row for.
_EMPTY_AGGREGATE = _Aggregate()


def money(value: DecimalInput) -> str:
    """Normalises an aggregate to a fixed-scale amount.

    The exact arithmetic happens in ``decimal.py`` on the digits themselves, and
    the string it produces is what the report publishes — round-tripping it
    through a ``Decimal`` would only give a later serialiser the chance to
    restate the scale.
    """
    return format_decimal(value)


def order_date_window(from_: Any, to: Any) -> ColumnElement[bool]:
    """Dates an order by ``placed_at``, falling back to ``created_at``.

    A draft order has no ``placed_at`` yet, so it is dated by the moment it was
    written instead — otherwise every draft would fall outside every window.
    """
    return or_(
        and_(Order.placed_at >= from_, Order.placed_at < to),
        and_(Order.placed_at.is_(None), Order.created_at >= from_, Order.created_at < to),
    )


def sales_summary_statement(query: SalesSummaryQuery) -> Select[Any]:
    """Revenue bucketed by day, week or month."""
    dated = func.coalesce(Order.placed_at, Order.created_at)
    # The bucket width is a bound parameter like everything else: it arrives as
    # a validated enum member, and it still never becomes SQL text.
    bucket = func.date_trunc(query.period.value, dated).label("bucket_start")

    criteria: list[ColumnElement[bool]] = [
        Order.deleted_at.is_(None),
        Order.status != OrderStatus.CANCELLED,
        dated >= query.from_,
        dated < query.to,
    ]
    if query.owner_id is not None:
        criteria.append(Order.owner_id == query.owner_id)

    return (
        select(
            bucket,
            func.count().label("order_count"),
            func.coalesce(func.sum(Order.total), 0).label("revenue"),
        )
        .where(*criteria)
        .group_by(bucket)
        .order_by(bucket.asc())
    )


def deal_funnel_statement(query: DealFunnelQuery, *, stage: DealStage | None = None) -> Select[Any]:
    """Deal counts and amounts per stage, optionally narrowed to one stage."""
    criteria: list[ColumnElement[bool]] = [
        # Soft-deleted deals are excluded from every funnel figure.
        Deal.deleted_at.is_(None),
        Deal.created_at >= query.from_,
        Deal.created_at < query.to,
    ]
    if query.owner_id is not None:
        criteria.append(Deal.owner_id == query.owner_id)
    if stage is not None:
        criteria.append(Deal.stage == stage)

    return (
        select(
            Deal.stage.label("stage"),
            func.count().label("row_count"),
            func.sum(Deal.amount).label("amount"),
        )
        .where(*criteria)
        .group_by(Deal.stage)
    )


def top_products_statement(query: TopProductsQuery) -> Select[Any]:
    """Sold quantity and revenue per product, richest first."""
    revenue = func.sum(OrderItem.line_total).label("revenue")
    return (
        select(
            OrderItem.product_id.label("product_id"),
            func.sum(OrderItem.quantity).label("quantity"),
            revenue,
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            # Cancelled and soft-deleted orders never count as sales.
            Order.deleted_at.is_(None),
            Order.status != OrderStatus.CANCELLED,
            order_date_window(query.from_, query.to),
        )
        .group_by(OrderItem.product_id)
        .order_by(revenue.desc())
        .limit(query.limit)
    )


def owner_deal_statement(
    query: OwnerPerformanceQuery, *, stage: DealStage | None = None
) -> Select[Any]:
    """Deal counts and amounts per owner, optionally narrowed to one stage."""
    criteria: list[ColumnElement[bool]] = [
        Deal.deleted_at.is_(None),
        Deal.created_at >= query.from_,
        Deal.created_at < query.to,
    ]
    if stage is not None:
        criteria.append(Deal.stage == stage)

    return (
        select(
            Deal.owner_id.label("owner_id"),
            func.count().label("row_count"),
            func.sum(Deal.amount).label("amount"),
        )
        .where(*criteria)
        .group_by(Deal.owner_id)
    )


def owner_order_statement(query: OwnerPerformanceQuery) -> Select[Any]:
    """Order counts and revenue per owner."""
    return (
        select(
            Order.owner_id.label("owner_id"),
            func.count().label("row_count"),
            func.sum(Order.total).label("amount"),
        )
        .where(
            Order.deleted_at.is_(None),
            Order.status != OrderStatus.CANCELLED,
            order_date_window(query.from_, query.to),
        )
        .group_by(Order.owner_id)
    )


def stock_health_statement(query: StockHealthQuery) -> Select[Any]:
    """Product-warehouse pairs whose free stock is at or below the threshold."""
    available = (StockLevel.quantity_on_hand - StockLevel.quantity_reserved).label(
        "quantity_available"
    )

    criteria: list[ColumnElement[bool]] = [
        Product.deleted_at.is_(None),
        Product.is_active.is_(True),
        available <= query.threshold,
    ]
    if query.warehouse_id is not None:
        criteria.append(StockLevel.warehouse_id == query.warehouse_id)

    return (
        select(
            Product.id.label("product_id"),
            Product.sku.label("sku"),
            Product.name.label("name"),
            Warehouse.id.label("warehouse_id"),
            Warehouse.code.label("warehouse_code"),
            StockLevel.quantity_on_hand.label("quantity_on_hand"),
            StockLevel.quantity_reserved.label("quantity_reserved"),
            available,
        )
        .select_from(StockLevel)
        .join(Product, Product.id == StockLevel.product_id)
        .join(Warehouse, Warehouse.id == StockLevel.warehouse_id)
        .where(*criteria)
        .order_by(available.asc(), Product.sku.asc())
        .limit(query.limit)
    )


class AnalyticsService:
    """Builds the five aggregate reports, through a cache.

    The cache is injectable so that tests, and any call site assembled without
    infrastructure, need no Redis: the no-op fallback turns every read into a
    miss and discards every write.
    """

    def __init__(
        self,
        session: AsyncSession,
        cache: AnalyticsCache | None = None,
        ttl_seconds: int = DEFAULT_ANALYTICS_TTL_SECONDS,
    ) -> None:
        self._session = session
        self._cache: AnalyticsCache = cache if cache is not None else NoopAnalyticsCache()
        self._ttl_seconds = ttl_seconds

    async def sales_summary(self, query: SalesSummaryQuery) -> SalesSummaryReport:
        key = analytics_report_key(
            SALES_SUMMARY_REPORT,
            {
                "from": format_datetime(query.from_),
                "to": format_datetime(query.to),
                "period": query.period.value,
                "ownerId": str(query.owner_id) if query.owner_id is not None else None,
            },
        )
        return await self._report(SalesSummaryReport, key, lambda: self._sales_summary(query))

    async def deal_funnel(self, query: DealFunnelQuery) -> DealFunnelReport:
        key = analytics_report_key(
            DEAL_FUNNEL_REPORT,
            {
                "from": format_datetime(query.from_),
                "to": format_datetime(query.to),
                "ownerId": str(query.owner_id) if query.owner_id is not None else None,
            },
        )
        return await self._report(DealFunnelReport, key, lambda: self._deal_funnel(query))

    async def top_products(self, query: TopProductsQuery) -> TopProductsReport:
        key = analytics_report_key(
            TOP_PRODUCTS_REPORT,
            {
                "from": format_datetime(query.from_),
                "to": format_datetime(query.to),
                "limit": query.limit,
            },
        )
        return await self._report(TopProductsReport, key, lambda: self._top_products(query))

    async def owner_performance(self, query: OwnerPerformanceQuery) -> OwnerPerformanceReport:
        key = analytics_report_key(
            OWNER_PERFORMANCE_REPORT,
            {
                "from": format_datetime(query.from_),
                "to": format_datetime(query.to),
                "limit": query.limit,
            },
        )
        return await self._report(
            OwnerPerformanceReport, key, lambda: self._owner_performance(query)
        )

    async def stock_health(self, query: StockHealthQuery) -> StockHealthReport:
        key = analytics_report_key(
            STOCK_HEALTH_REPORT,
            {
                "threshold": query.threshold,
                "limit": query.limit,
                "warehouseId": str(query.warehouse_id) if query.warehouse_id is not None else None,
            },
        )
        return await self._report(StockHealthReport, key, lambda: self._stock_health(query))

    async def _sales_summary(self, query: SalesSummaryQuery) -> SalesSummaryReport:
        rows = (await self._session.execute(sales_summary_statement(query))).all()

        series = [
            SalesSummaryBucket(
                bucket_start=row.bucket_start,
                order_count=int(row.order_count or 0),
                revenue=money(row.revenue),
            )
            for row in rows
        ]

        order_count = sum(bucket.order_count for bucket in series)
        revenue = sum_decimals([bucket.revenue for bucket in series])

        return SalesSummaryReport(
            from_=query.from_,
            to=query.to,
            period=query.period,
            totals=SalesSummaryTotals(
                order_count=order_count,
                revenue=revenue,
                average_order_value=average_decimal(revenue, order_count),
            ),
            series=series,
        )

    async def _deal_funnel(self, query: DealFunnelQuery) -> DealFunnelReport:
        rows = (await self._session.execute(deal_funnel_statement(query))).all()
        # A stage with no deals produces no row, so the report is built from the
        # full list of stages rather than from what the query happened to return.
        by_stage: dict[DealStage, _Aggregate] = {
            DealStage(row.stage): _Aggregate(count=row.row_count, amount=row.amount) for row in rows
        }

        stages = [
            DealFunnelStage(
                stage=stage,
                count=by_stage.get(stage, _EMPTY_AGGREGATE).count_value,
                amount=money(by_stage.get(stage, _EMPTY_AGGREGATE).amount),
            )
            for stage in DealStage
        ]
        count_by_stage = {entry.stage: entry.count for entry in stages}

        conversions = [
            DealFunnelConversion(
                from_=source,
                to=target,
                # An empty source stage yields 0 rather than a division error.
                rate=ratio(count_by_stage.get(target, 0), count_by_stage.get(source, 0)),
            )
            for source, target in itertools.pairwise(FUNNEL_PIPELINE)
        ]

        return DealFunnelReport(
            from_=query.from_, to=query.to, stages=stages, conversions=conversions
        )

    async def _top_products(self, query: TopProductsQuery) -> TopProductsReport:
        rows = (await self._session.execute(top_products_statement(query))).all()

        product_ids = [row.product_id for row in rows]
        # Products removed from the catalogue after the sale are still labelled,
        # otherwise historic revenue would lose its name.
        by_id = await self._products_by_id(product_ids)

        items = [
            TopProductRow(
                product_id=row.product_id,
                sku=by_id[row.product_id].sku if row.product_id in by_id else "",
                name=by_id[row.product_id].name if row.product_id in by_id else "",
                quantity=int(row.quantity or 0),
                revenue=money(row.revenue),
            )
            for row in rows
        ]

        return TopProductsReport(from_=query.from_, to=query.to, limit=query.limit, items=items)

    async def _owner_performance(self, query: OwnerPerformanceQuery) -> OwnerPerformanceReport:
        # Run one after another rather than concurrently: a session is a single
        # connection, and issuing three statements on it at once is a protocol
        # error rather than a speed-up.
        deal_rows = (await self._session.execute(owner_deal_statement(query))).all()
        won_rows = (
            await self._session.execute(owner_deal_statement(query, stage=DealStage.WON))
        ).all()
        order_rows = (await self._session.execute(owner_order_statement(query))).all()

        deal_by_owner = {row.owner_id: _Aggregate(row.row_count, row.amount) for row in deal_rows}
        won_by_owner = {row.owner_id: _Aggregate(row.row_count, row.amount) for row in won_rows}
        order_by_owner = {row.owner_id: _Aggregate(row.row_count, row.amount) for row in order_rows}

        # An owner appears if they hold deals or orders; the won-deal query can
        # only ever name owners the deal query already did.
        owner_ids = list(dict.fromkeys([*deal_by_owner, *order_by_owner]))
        owners = await self._users_by_id(owner_ids)

        items: list[OwnerPerformanceRow] = []
        for owner_id in owner_ids:
            deals = deal_by_owner.get(owner_id, _EMPTY_AGGREGATE)
            won = won_by_owner.get(owner_id, _EMPTY_AGGREGATE)
            orders = order_by_owner.get(owner_id, _EMPTY_AGGREGATE)
            owner = owners.get(owner_id)
            items.append(
                OwnerPerformanceRow(
                    owner_id=owner_id,
                    # An owner deleted from the directory keeps their figures:
                    # the work happened, only the label is gone.
                    name=owner.name if owner is not None else None,
                    email=owner.email if owner is not None else None,
                    deal_count=deals.count_value,
                    deal_amount=money(deals.amount),
                    won_deal_count=won.count_value,
                    won_deal_amount=money(won.amount),
                    win_rate=ratio(won.count_value, deals.count_value),
                    order_count=orders.count_value,
                    order_revenue=money(orders.amount),
                )
            )

        # Ranked by order revenue as exact integers, then cut to the page: the
        # ranking is over every owner, not over an arbitrary first slice.
        ranked = sorted(items, key=lambda row: to_scaled_integer(row.order_revenue), reverse=True)
        return OwnerPerformanceReport(from_=query.from_, to=query.to, items=ranked[: query.limit])

    async def _stock_health(self, query: StockHealthQuery) -> StockHealthReport:
        rows = (await self._session.execute(stock_health_statement(query))).all()

        items = [
            StockHealthRow(
                product_id=row.product_id,
                sku=row.sku,
                name=row.name,
                warehouse_id=row.warehouse_id,
                warehouse_code=row.warehouse_code,
                quantity_on_hand=int(row.quantity_on_hand or 0),
                quantity_reserved=int(row.quantity_reserved or 0),
                quantity_available=int(row.quantity_available or 0),
            )
            for row in rows
        ]

        return StockHealthReport(threshold=query.threshold, limit=query.limit, items=items)

    async def _products_by_id(self, product_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Product]:
        """Labels for the ranked products; skipped entirely when nothing sold."""
        if not product_ids:
            return {}
        result = await self._session.execute(
            select(Product).where(Product.id.in_(list(product_ids)))
        )
        return {product.id: product for product in result.scalars().all()}

    async def _users_by_id(self, owner_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, User]:
        """Names for the ranked owners; skipped entirely when nobody qualifies."""
        if not owner_ids:
            return {}
        result = await self._session.execute(select(User).where(User.id.in_(list(owner_ids))))
        return {user.id: user for user in result.scalars().all()}

    async def _report[T: BaseModel](
        self,
        model: type[T],
        key: str,
        load: Callable[[], Awaitable[T]],
    ) -> T:
        """Serves a report from the cache, otherwise builds and stores it.

        The stored form is the published JSON document, so a cache entry is
        exactly the body the client would have received; an entry written by an
        older version of this code fails to validate and is treated as a miss.
        """

        async def loader() -> Any:
            report = await load()
            return report.model_dump(mode="json", by_alias=True)

        payload = await self._remember_safely(key, loader)
        try:
            return model.model_validate(payload)
        except ValidationError:
            return await load()

    async def _remember_safely[T](self, key: str, loader: Callable[[], Awaitable[T]]) -> T:
        """Reads through the cache, treating a cache outage as latency only.

        The loader runs at most once, so a genuine database failure still
        surfaces to the caller instead of being retried behind their back.
        """
        loader_ran = False

        async def guarded() -> T:
            nonlocal loader_ran
            loader_ran = True
            return await loader()

        try:
            return await self._cache.remember(key, self._ttl_seconds, guarded)
        except Exception:
            if loader_ran:
                raise
            return await loader()
