"""Wire contract of the analytics endpoints.

Two things are worth stating before the code.

A date range is *normalised*, not merely validated: a caller may send neither
bound, either one, or both, and what reaches the service is always a resolved
half-open interval ``[from, to)`` in UTC. That is what lets a cache key be built
from the query — two requests that mean the same window produce the same key
however the client spelled it.

A limit is clamped rather than rejected. A caller asking for "everything" gets
the largest page the report is willing to build instead of an error, while the
ceiling still holds and one request can never table-scan years of history.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from pydantic import AfterValidator, Field, PrivateAttr, model_validator

from app.core.reporting import (
    DEFAULT_REPORT_WINDOW_FROM,
    MAX_REPORT_WINDOW_DAYS,
    default_report_window_to,
)
from app.core.responses import CamelModel
from app.core.serializers import UtcDatetime
from app.db.enums import DealStage
from app.modules.analytics.types import (
    AnalyticsPeriod,
    DealFunnelQuery,
    OwnerPerformanceQuery,
    SalesSummaryQuery,
    StockHealthQuery,
    TopProductsQuery,
)

__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_RANGE_FROM",
    "DEFAULT_STOCK_THRESHOLD",
    "MAX_LIMIT",
    "MAX_RANGE_DAYS",
    "MAX_STOCK_THRESHOLD",
    "DealFunnelConversion",
    "DealFunnelParams",
    "DealFunnelReport",
    "DealFunnelStage",
    "OwnerPerformanceParams",
    "OwnerPerformanceReport",
    "OwnerPerformanceRow",
    "SalesSummaryBucket",
    "SalesSummaryParams",
    "SalesSummaryReport",
    "SalesSummaryTotals",
    "StockHealthParams",
    "StockHealthReport",
    "StockHealthRow",
    "TopProductRow",
    "TopProductsParams",
    "TopProductsReport",
]

#: Widest window a single report may scan. See ``app.core.reporting``.
MAX_RANGE_DAYS = MAX_REPORT_WINDOW_DAYS
#: Start of the window applied when the caller does not name one; the end is
#: today. See ``app.core.reporting``.
DEFAULT_RANGE_FROM = DEFAULT_REPORT_WINDOW_FROM
#: Hard ceiling for every ``limit``; larger values are clamped, not rejected.
MAX_LIMIT = 100
DEFAULT_LIMIT = 10
MAX_STOCK_THRESHOLD = 1_000_000
DEFAULT_STOCK_THRESHOLD = 5

#: A figure in a report, always at the fixed scale ``decimal.py`` produces.
#:
#: Deliberately *not* the ``Money`` of a persisted record: a stored amount is
#: rendered in shortest exact form, while a report column is a computed
#: aggregate that keeps its two decimals so a column of figures lines up. The
#: value is already a string by the time it reaches this model — the arithmetic
#: in ``decimal.py`` never leaves exact integers — so no serialiser is involved.
#:
#: A plain assignment rather than a ``type`` statement: the latter would publish
#: itself as a named component and put a ``$ref`` where the contract has an
#: inline ``string``.
ReportMoney = str


def _clamp_limit(value: int) -> int:
    return min(value, MAX_LIMIT)


def _clamp_threshold(value: int) -> int:
    return min(value, MAX_STOCK_THRESHOLD)


#: A page size that is bounded on both ends: below one is a mistake, above the
#: ceiling is a request for the ceiling.
BoundedLimit = Annotated[int, Field(ge=1), AfterValidator(_clamp_limit)]

#: A stock threshold; zero is meaningful — "show me what is already out".
BoundedThreshold = Annotated[int, Field(ge=0), AfterValidator(_clamp_threshold)]


#: The reports are stored with millisecond precision, so anything finer in a
#: bound cannot change which rows match — but it *can* change the answer while
#: leaving the cache key identical, which would let one key hold two different
#: result sets. Bounds are therefore truncated to the stored resolution.
_MICROSECONDS_PER_MILLISECOND = 1_000


def _as_utc(value: datetime) -> datetime:
    """Reads a bound as UTC, at the resolution the data is stored in.

    A client may send ``2026-01-01``, which parses without a zone. Treating that
    as local time would move the window by the server's offset, so a missing
    zone is read as UTC rather than as "wherever this process happens to run".
    """
    resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    microsecond = (
        resolved.microsecond // _MICROSECONDS_PER_MILLISECOND
    ) * _MICROSECONDS_PER_MILLISECOND
    return resolved.replace(microsecond=microsecond)


class DateRangeParams(CamelModel):
    """The ``from``/``to`` pair every time-bounded report accepts.

    Both bounds stay optional on the wire and are resolved during validation, so
    a handler is never handed a half-specified window.
    """

    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None

    #: The resolved window. Held privately rather than written back over the
    #: optional fields, so the published query schema keeps saying "optional"
    #: while the rest of the module reads a bound that is always present.
    _range_from: datetime = PrivateAttr()
    _range_to: datetime = PrivateAttr()

    @model_validator(mode="after")
    def _resolve_range(self) -> DateRangeParams:
        # Each bound defaults on its own, so a caller may send neither, either,
        # or both. The start is fixed and the end is the close of today, so a
        # report asked for without a window includes what was entered today.
        to = _as_utc(self.to) if self.to is not None else default_report_window_to()
        from_ = _as_utc(self.from_) if self.from_ is not None else DEFAULT_RANGE_FROM

        if from_ >= to:
            message = "from must be earlier than to"
            raise ValueError(message)
        if to - from_ > timedelta(days=MAX_RANGE_DAYS):
            message = f"The date range must not exceed {MAX_RANGE_DAYS} days"
            raise ValueError(message)

        self._range_from = from_
        self._range_to = to
        return self

    @property
    def range_from(self) -> datetime:
        """Resolved lower bound of the half-open interval."""
        return self._range_from

    @property
    def range_to(self) -> datetime:
        """Resolved upper bound of the half-open interval."""
        return self._range_to


class SalesSummaryParams(DateRangeParams):
    """Query string of ``GET /analytics/sales-summary``."""

    period: AnalyticsPeriod = AnalyticsPeriod.DAY
    owner_id: uuid.UUID | None = None

    def to_query(self) -> SalesSummaryQuery:
        return SalesSummaryQuery(
            from_=self.range_from,
            to=self.range_to,
            period=self.period,
            owner_id=self.owner_id,
        )


class DealFunnelParams(DateRangeParams):
    """Query string of ``GET /analytics/deal-funnel``."""

    owner_id: uuid.UUID | None = None

    def to_query(self) -> DealFunnelQuery:
        return DealFunnelQuery(from_=self.range_from, to=self.range_to, owner_id=self.owner_id)


class TopProductsParams(DateRangeParams):
    """Query string of ``GET /analytics/top-products``."""

    limit: BoundedLimit = DEFAULT_LIMIT

    def to_query(self) -> TopProductsQuery:
        return TopProductsQuery(from_=self.range_from, to=self.range_to, limit=self.limit)


class OwnerPerformanceParams(DateRangeParams):
    """Query string of ``GET /analytics/owner-performance``."""

    limit: BoundedLimit = DEFAULT_LIMIT

    def to_query(self) -> OwnerPerformanceQuery:
        return OwnerPerformanceQuery(from_=self.range_from, to=self.range_to, limit=self.limit)


class StockHealthParams(CamelModel):
    """Query string of ``GET /analytics/stock-health``.

    The only report with no date range: it describes the present, and asking for
    "the stock as it was in March" would be a different question entirely.
    """

    threshold: BoundedThreshold = DEFAULT_STOCK_THRESHOLD
    limit: BoundedLimit = DEFAULT_LIMIT
    warehouse_id: uuid.UUID | None = None

    def to_query(self) -> StockHealthQuery:
        return StockHealthQuery(
            threshold=self.threshold, limit=self.limit, warehouse_id=self.warehouse_id
        )


class SalesSummaryBucket(CamelModel):
    """One bucket of the revenue series."""

    bucket_start: UtcDatetime
    order_count: int
    revenue: ReportMoney


class SalesSummaryTotals(CamelModel):
    """The whole window rolled into one row."""

    order_count: int
    revenue: ReportMoney
    average_order_value: ReportMoney


class SalesSummaryReport(CamelModel):
    """Body of ``GET /analytics/sales-summary``."""

    from_: UtcDatetime = Field(alias="from")
    to: UtcDatetime
    period: AnalyticsPeriod
    totals: SalesSummaryTotals
    series: list[SalesSummaryBucket]


class DealFunnelStage(CamelModel):
    """How much sits in one stage of the pipeline."""

    stage: DealStage
    count: int
    amount: ReportMoney


class DealFunnelConversion(CamelModel):
    """How much of one stage reached the next."""

    from_: DealStage = Field(alias="from")
    to: DealStage
    #: Ratio in ``[0, 1]``, rounded to four decimals; 0 when the source is empty.
    rate: float


class DealFunnelReport(CamelModel):
    """Body of ``GET /analytics/deal-funnel``."""

    from_: UtcDatetime = Field(alias="from")
    to: UtcDatetime
    stages: list[DealFunnelStage]
    conversions: list[DealFunnelConversion]


class TopProductRow(CamelModel):
    """One product in the revenue ranking."""

    product_id: uuid.UUID
    sku: str
    name: str
    quantity: int
    revenue: ReportMoney


class TopProductsReport(CamelModel):
    """Body of ``GET /analytics/top-products``."""

    from_: UtcDatetime = Field(alias="from")
    to: UtcDatetime
    limit: int
    items: list[TopProductRow]


class OwnerPerformanceRow(CamelModel):
    """One owner's deals and orders over the window."""

    owner_id: uuid.UUID
    name: str | None
    email: str | None
    deal_count: int
    deal_amount: ReportMoney
    won_deal_count: int
    won_deal_amount: ReportMoney
    win_rate: float
    order_count: int
    order_revenue: ReportMoney


class OwnerPerformanceReport(CamelModel):
    """Body of ``GET /analytics/owner-performance``."""

    from_: UtcDatetime = Field(alias="from")
    to: UtcDatetime
    items: list[OwnerPerformanceRow]


class StockHealthRow(CamelModel):
    """One product-warehouse pair at or below the threshold."""

    product_id: uuid.UUID
    sku: str
    name: str
    warehouse_id: uuid.UUID
    warehouse_code: str
    quantity_on_hand: int
    quantity_reserved: int
    quantity_available: int


class StockHealthReport(CamelModel):
    """Body of ``GET /analytics/stock-health``."""

    threshold: int
    limit: int
    items: list[StockHealthRow]
