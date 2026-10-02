"""The published description names the refusals the service can answer with.

The generator derives the routes and the request and response shapes from the
code, but it cannot see an exception raised in a service below the handler.
Those refusals are declared by hand, so they can be forgotten; these rules catch
the forgetting that has a mechanical signature.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from app.container import build_container
from app.core.settings import Settings
from app.factory import create_app

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql://user:pass@localhost:5432/practice_crm_test?schema=public",
        jwt_access_secret="test-secret-value-that-is-long-enough",
        jwt_refresh_secret="test-secret-value-that-is-long-enough",
        redis_url="redis://localhost:6379",
        mongodb_url="mongodb://localhost:27017/practice_events_test",
    )
    container = build_container(settings)
    return create_app(settings, routers=container.routers).openapi()


def _operations(schema: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (f"{method.upper()} {path}", operation)
        for path, item in schema["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    ]


def _body_schema(schema: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    body = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
    reference = body.get("schema", {}).get("$ref")
    if reference is None:
        return cast("dict[str, Any]", body.get("schema", {}))
    return cast("dict[str, Any]", schema["components"]["schemas"][reference.rsplit("/", 1)[-1]])


def _carries_a_version(schema: dict[str, Any], operation: dict[str, Any]) -> bool:
    in_query = any(parameter["name"] == "version" for parameter in operation.get("parameters", []))
    in_body = "version" in _body_schema(schema, operation).get("properties", {})
    return in_query or in_body


def test_an_operation_that_takes_a_version_documents_the_conflict(
    schema: dict[str, Any],
) -> None:
    """A version is sent only so a stale one can be refused with 409."""
    versioned = [
        (name, operation)
        for name, operation in _operations(schema)
        if _carries_a_version(schema, operation)
    ]
    undocumented = [name for name, operation in versioned if "409" not in operation["responses"]]

    # Not vacuous: optimistic locking is spread across the whole API.
    assert len(versioned) >= 10
    assert undocumented == []


def test_a_secured_operation_documents_the_missing_token(schema: dict[str, Any]) -> None:
    undocumented = [
        name
        for name, operation in _operations(schema)
        if operation.get("security") and "401" not in operation["responses"]
    ]

    assert undocumented == []


def test_the_versioned_product_update_documents_its_conflict(schema: dict[str, Any]) -> None:
    """The case that showed the gap: a stale version answers 409."""
    responses = schema["paths"]["/api/v1/products/{product_id}"]["patch"]["responses"]

    assert responses["409"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }


def test_a_declared_refusal_survives_while_the_framework_422_does_not(
    schema: dict[str, Any],
) -> None:
    match = schema["paths"]["/api/v1/finance/transactions/{id}/match"]["post"]["responses"]

    assert "422" in match
    assert "HTTPValidationError" not in schema["components"]["schemas"]
