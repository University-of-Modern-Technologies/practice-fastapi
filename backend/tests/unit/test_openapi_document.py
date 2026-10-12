"""The committed ``openapi.json`` is the description the code actually produces.

The document is generated, never edited by hand, and committed so a reviewer
sees how a change moves the published contract. Two things can make it lie: a
change to the code without regenerating the file, and a route the generator
never sees. Each has its own check here.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from starlette.routing import Match
from starlette.types import Scope

from app.core.openapi import RESPONSE_DESCRIPTIONS
from scripts.export_openapi import (
    EXPORT_COMMAND,
    OUTPUT_PATH,
    build_app,
    render_document,
)

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

# Served on purpose without a description. A route lands here only by a
# reviewed decision; anything else that is mounted has to be described.
UNDOCUMENTED_ROUTES = {
    ("GET", "/api/openapi.json"),
    ("GET", "/api/docs"),
    ("GET", "/api/docs/oauth2-redirect"),
    ("GET", "/api/docs/swagger-ui-bundle.js"),
    ("GET", "/api/docs/swagger-ui.css"),
    ("GET", "/api/docs/favicon.png"),
    ("GET", "/api/health/startup"),
    ("GET", "/api/health/info"),
}

_SAMPLE_PATH_VALUE = str(uuid.UUID(int=1))


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return build_app()


@pytest.fixture(scope="module")
def document(app: FastAPI) -> dict[str, Any]:
    return app.openapi()


def _described(document: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, item in document["paths"].items()
        for method in item
        if method in HTTP_METHODS
    }


def _mounted(app: FastAPI) -> set[tuple[str, str]]:
    mounted: set[tuple[str, str]] = set()
    for route in iter_route_contexts(app.routes):
        # A WebSocket endpoint has no methods: it is not an HTTP operation.
        if route.methods is None or route.path_format is None:
            continue
        mounted.update((method, route.path_format) for method in route.methods - {"HEAD"})
    return mounted


def _first_difference(committed: str, generated: str) -> str:
    for number, (old, new) in enumerate(
        zip(committed.splitlines(), generated.splitlines(), strict=False), start=1
    ):
        if old != new:
            return f"line {number}: committed {old.strip()!r}, generated {new.strip()!r}"
    return "one of the two ends early"


def test_the_committed_document_matches_the_code(document: dict[str, Any]) -> None:
    generated = render_document(document)
    hint = f"run `{EXPORT_COMMAND}` in the backend folder and commit {OUTPUT_PATH.name}"

    if not OUTPUT_PATH.is_file():
        pytest.fail(f"{OUTPUT_PATH.name} is missing: {hint}")

    # Read as text, so a checkout with CRLF line endings compares equal.
    committed = OUTPUT_PATH.read_text(encoding="utf-8")
    if committed != generated:
        pytest.fail(
            f"{OUTPUT_PATH.name} is out of date with the code "
            f"({_first_difference(committed, generated)}): {hint}"
        )


def test_every_mounted_route_is_described(app: FastAPI, document: dict[str, Any]) -> None:
    undescribed = _mounted(app) - _described(document) - UNDOCUMENTED_ROUTES

    assert undescribed == set()


def test_every_route_kept_out_of_the_description_is_still_mounted(app: FastAPI) -> None:
    """A stale entry in the list above would hide the next route that takes its place."""
    assert UNDOCUMENTED_ROUTES - _mounted(app) == set()


def test_the_document_keeps_the_hidden_routes_out(document: dict[str, Any]) -> None:
    assert _described(document) & UNDOCUMENTED_ROUTES == set()


def _is_served(app: FastAPI, method: str, path: str) -> bool:
    concrete = path
    for name in (part[1:-1] for part in path.split("/") if part.startswith("{")):
        concrete = concrete.replace(f"{{{name}}}", _SAMPLE_PATH_VALUE)
    scope: Scope = {"type": "http", "method": method, "path": concrete, "root_path": ""}
    return any(route.matches(scope)[0] == Match.FULL for route in app.routes)


def test_every_described_operation_is_served(app: FastAPI, document: dict[str, Any]) -> None:
    """Checked through the router's own matching, not through the generator."""
    described = _described(document)
    unserved = sorted(
        (method, path) for method, path in described if not _is_served(app, method, path)
    )

    # Not vacuous: the whole business API is described.
    assert len(described) >= 50
    assert unserved == []


def _operations(document: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (method, path, operation)
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    ]


def test_every_operation_is_named_by_its_method_and_path(document: dict[str, Any]) -> None:
    """One rule for both backends: ``GET /api/v1/products/{id}`` → ``get_api_v1_products_id``."""
    misnamed = []
    for method, path, operation in _operations(document):
        expected = re.sub(r"[^a-z0-9]+", "_", f"{method}_{path}".lower()).strip("_")
        if operation.get("operationId") != expected:
            misnamed.append((method, path, operation.get("operationId")))

    assert misnamed == []


def test_the_operation_names_are_unique(document: dict[str, Any]) -> None:
    names = [operation["operationId"] for _, _, operation in _operations(document)]

    assert len(names) == len(set(names))


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("get", "/api/v1/products/{id}", "get_api_v1_products_id"),
        (
            "delete",
            "/api/v1/users/{id}/sessions/{sessionId}",
            "delete_api_v1_users_id_sessions_sessionid",
        ),
        ("get", "/api/v1/analytics/{report}/export", "get_api_v1_analytics_report_export"),
        ("get", "/api/health/live", "get_api_health_live"),
    ],
)
def test_an_operation_name_folds_every_separator_into_one_underscore(
    document: dict[str, Any], method: str, path: str, expected: str
) -> None:
    assert document["paths"][path][method]["operationId"] == expected


def test_every_business_operation_declares_the_invalid_request(
    document: dict[str, Any],
) -> None:
    error = {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
    business = [
        (method, path, operation)
        for method, path, operation in _operations(document)
        if path.startswith("/api/v1/")
    ]
    undeclared = [
        (method, path)
        for method, path, operation in business
        if operation["responses"].get("400")
        != {"description": RESPONSE_DESCRIPTIONS[400], "content": error}
    ]

    assert len(business) >= 50
    assert undeclared == []


def test_every_operation_declares_the_internal_error(document: dict[str, Any]) -> None:
    error = {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
    undeclared = [
        (method, path)
        for method, path, operation in _operations(document)
        if operation["responses"].get("500")
        != {"description": RESPONSE_DESCRIPTIONS[500], "content": error}
    ]

    assert undeclared == []


def test_a_probe_without_input_declares_no_invalid_request(document: dict[str, Any]) -> None:
    probes = [
        operation for _, path, operation in _operations(document) if path.startswith("/api/health/")
    ]

    assert len(probes) == 2
    assert all("parameters" not in operation for operation in probes)
    assert all("400" not in operation["responses"] for operation in probes)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/products/{id}",
        "/api/v1/users/{id}/sessions/{sessionId}",
        "/api/v1/orders/{id}/items/{itemId}",
        "/api/v1/audit/{resource}/{resourceId}",
        "/api/v1/audit/{id}",
        "/api/v1/warehouse/stock/{warehouseId}/{productId}",
    ],
)
def test_a_path_parameter_carries_the_contract_name(document: dict[str, Any], path: str) -> None:
    placeholders = re.findall(r"\{([^}]+)\}", path)
    for operation in document["paths"][path].values():
        declared = [p["name"] for p in operation["parameters"] if p["in"] == "path"]
        assert declared == placeholders
