"""The export is described from the same models that validate and build it.

The handler reads its query by hand and writes its body by hand, so the
framework sees neither. The description is assembled from the descriptors
instead, and these tests hold the descriptors to what the export really does.
"""

from __future__ import annotations

import typing
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi

from app.modules.analytics.export import ANALYTICS_EXPORT_DESCRIPTORS, EXPORT_FORMATS
from app.modules.analytics.router import create_analytics_router
from app.modules.analytics.schemas import AnalyticsExportRow, AnalyticsExportRows

EXPORT_PATH = "/api/v1/analytics/{report}/export"


@pytest.fixture(scope="module")
def operation() -> dict[str, Any]:
    app = FastAPI()
    router: APIRouter = create_analytics_router()
    app.include_router(router, prefix="/api/v1/analytics")
    document = get_openapi(title="test", version="0", routes=app.routes)
    return typing.cast("dict[str, Any]", document["paths"][EXPORT_PATH]["get"])


def _aliases(model: Any) -> set[str]:
    return {field.alias or name for name, field in model.model_fields.items()}


@pytest.mark.parametrize("report", list(ANALYTICS_EXPORT_DESCRIPTORS))
def test_a_report_exports_the_columns_of_its_row(report: str) -> None:
    descriptor = ANALYTICS_EXPORT_DESCRIPTORS[report]

    assert set(descriptor.columns) == _aliases(descriptor.row_model)


def test_the_published_row_is_one_of_the_rows_the_reports_export() -> None:
    published = set(typing.get_args(AnalyticsExportRow))
    exported = {descriptor.row_model for descriptor in ANALYTICS_EXPORT_DESCRIPTORS.values()}

    assert published == exported
    assert AnalyticsExportRows.model_fields["data"].annotation == list[AnalyticsExportRow]


def test_the_published_query_is_the_format_and_every_report_query(
    operation: dict[str, Any],
) -> None:
    query = {p["name"]: p for p in operation["parameters"] if p["in"] == "query"}
    accepted = set().union(
        *(_aliases(d.params_model) for d in ANALYTICS_EXPORT_DESCRIPTORS.values())
    )

    assert set(query) == {"format"} | accepted
    # Every report query is optional, and the export adds nothing required.
    assert not any(parameter["required"] for parameter in query.values())
    assert query["format"]["schema"]["enum"] == list(EXPORT_FORMATS)


def test_the_published_query_carries_no_dangling_reference(operation: dict[str, Any]) -> None:
    assert "$ref" not in str(operation["parameters"])


def test_the_published_report_names_are_the_exported_ones(operation: dict[str, Any]) -> None:
    (report,) = [p for p in operation["parameters"] if p["in"] == "path"]

    assert report["schema"]["enum"] == list(ANALYTICS_EXPORT_DESCRIPTORS)


def test_both_formats_are_published_for_the_success(operation: dict[str, Any]) -> None:
    content = operation["responses"]["200"]["content"]

    assert content["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AnalyticsExportRows"
    }
    assert content["text/csv"]["schema"] == {"type": "string"}
