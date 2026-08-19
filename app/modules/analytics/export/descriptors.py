"""What each of the five reports exports.

A descriptor validates the same query its JSON sibling accepts, runs the same
service method, and names which array in the resulting report becomes the
exported table and in what column order. It never decides how that table is
rendered — that is `csv.py`'s job — so a report definition here is unaware
that CSV even exists.

Rows are taken from `report.model_dump(mode="json", by_alias=True)` rather
than read off the model's attributes directly. That is deliberate: it is the
exact serialisation FastAPI already uses to build the JSON response body, so
a money figure in the CSV is, by construction, the same string the JSON
report would have printed for it — there is no second formatting step that
could quietly disagree with the first.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.errors import ValidationFailedError
from app.core.handlers import flatten_validation_errors
from app.modules.analytics.schemas import (
    DealFunnelParams,
    OwnerPerformanceParams,
    SalesSummaryParams,
    StockHealthParams,
    TopProductsParams,
)
from app.modules.analytics.service import AnalyticsService

__all__ = [
    "ANALYTICS_EXPORT_DESCRIPTORS",
    "EXPORT_FORMATS",
    "AnalyticsExportDescriptor",
    "ExportFormat",
]

#: The two formats `GET /{report}/export` understands; `csv` is the default.
EXPORT_FORMATS = ("csv", "json")
ExportFormat = str


@dataclass(frozen=True, slots=True)
class AnalyticsExportDescriptor:
    """One report's export: its file name, its column order, and its loader.

    `load_rows` closes over the report-specific query model and service call,
    so the router that uses this descriptor never has to know which report it
    is talking to beyond the path segment that selected it.
    """

    file_stem: str
    columns: tuple[str, ...]
    load_rows: Callable[[AnalyticsService, dict[str, str]], Awaitable[list[dict[str, Any]]]]


def _query_errors(exc: ValidationError) -> dict[str, Any]:
    """Reshapes a `ValidationError` into the envelope FastAPI itself would use.

    A parameter validated here by hand still has to fail the same way a
    parameter FastAPI validated through `Query()` would: both are "the query
    was wrong" to the client, and prefixing the location with `query` is what
    the shared flattening helper needs to group it correctly.
    """
    errors = [{**error, "loc": ("query", *error.get("loc", ()))} for error in exc.errors()]
    return flatten_validation_errors(errors)


@dataclass(frozen=True, slots=True)
class _ReportBinding[Params: BaseModel, Query, Report: BaseModel]:
    """How to go from a raw query dict to a validated report.

    Bundled into one value so `_define_descriptor` takes a report's plumbing
    as a single argument rather than three, leaving room for the two things
    that actually vary the export's shape: the row array and the columns.
    """

    params_model: type[Params]
    to_query: Callable[[Params], Query]
    run: Callable[[AnalyticsService, Query], Awaitable[Report]]


def _define_descriptor(
    *,
    file_stem: str,
    binding: _ReportBinding[Any, Any, Any],
    rows_field: str,
    columns: tuple[str, ...],
) -> AnalyticsExportDescriptor:
    async def load_rows(
        service: AnalyticsService, raw_query: dict[str, str]
    ) -> list[dict[str, Any]]:
        try:
            params = binding.params_model.model_validate(raw_query)
        except ValidationError as exc:
            raise ValidationFailedError(details=_query_errors(exc)) from exc

        report = await binding.run(service, binding.to_query(params))
        dumped = report.model_dump(mode="json", by_alias=True)
        rows = dumped[rows_field]
        return list(rows)

    return AnalyticsExportDescriptor(file_stem=file_stem, columns=columns, load_rows=load_rows)


_sales_summary = _define_descriptor(
    file_stem="sales-summary",
    binding=_ReportBinding(
        params_model=SalesSummaryParams,
        to_query=SalesSummaryParams.to_query,
        run=lambda service, query: service.sales_summary(query),
    ),
    rows_field="series",
    columns=("bucketStart", "orderCount", "revenue"),
)

_deal_funnel = _define_descriptor(
    file_stem="deal-funnel",
    binding=_ReportBinding(
        params_model=DealFunnelParams,
        to_query=DealFunnelParams.to_query,
        run=lambda service, query: service.deal_funnel(query),
    ),
    rows_field="stages",
    columns=("stage", "count", "amount"),
)

_top_products = _define_descriptor(
    file_stem="top-products",
    binding=_ReportBinding(
        params_model=TopProductsParams,
        to_query=TopProductsParams.to_query,
        run=lambda service, query: service.top_products(query),
    ),
    rows_field="items",
    columns=("productId", "sku", "name", "quantity", "revenue"),
)

_owner_performance = _define_descriptor(
    file_stem="owner-performance",
    binding=_ReportBinding(
        params_model=OwnerPerformanceParams,
        to_query=OwnerPerformanceParams.to_query,
        run=lambda service, query: service.owner_performance(query),
    ),
    rows_field="items",
    columns=(
        "ownerId",
        "name",
        "email",
        "dealCount",
        "dealAmount",
        "wonDealCount",
        "wonDealAmount",
        "winRate",
        "orderCount",
        "orderRevenue",
    ),
)

_stock_health = _define_descriptor(
    file_stem="stock-health",
    binding=_ReportBinding(
        params_model=StockHealthParams,
        to_query=StockHealthParams.to_query,
        run=lambda service, query: service.stock_health(query),
    ),
    rows_field="items",
    columns=(
        "productId",
        "sku",
        "name",
        "warehouseId",
        "warehouseCode",
        "quantityOnHand",
        "quantityReserved",
        "quantityAvailable",
    ),
)

#: Keyed by the same kebab-case segment the JSON routes already use.
ANALYTICS_EXPORT_DESCRIPTORS: dict[str, AnalyticsExportDescriptor] = {
    "sales-summary": _sales_summary,
    "deal-funnel": _deal_funnel,
    "top-products": _top_products,
    "owner-performance": _owner_performance,
    "stock-health": _stock_health,
}
