"""Metric recording, label cardinality and the guarded scrape endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from prometheus_client import CollectorRegistry

from app.core.settings import Settings
from app.factory import create_app
from app.middleware.metrics import MetricsMiddleware
from app.observability.metrics import (
    UNMATCHED_ROUTE_LABEL,
    create_http_metrics,
    resolve_route_label,
)
from app.observability.registry import (
    PROMETHEUS_CONTENT_TYPE,
    create_metrics_registry,
    register_process_metrics,
    render_metrics,
)
from app.observability.routes import create_metrics_router

METRICS_TOKEN = "metrics-token-long-enough"


def _create_probe_router() -> APIRouter:
    router = APIRouter()

    @router.get("/items/{item_id}")
    async def read_item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    @router.get("/boom")
    async def boom() -> None:
        message = "probe failure"
        raise RuntimeError(message)

    return router


@pytest.fixture
def registry() -> CollectorRegistry:
    return create_metrics_registry()


@pytest.fixture
def metrics_app(settings: Settings, registry: CollectorRegistry) -> FastAPI:
    metrics = create_http_metrics(registry)
    register_process_metrics(registry)

    app = create_app(
        settings,
        routers=[
            ("/probe", _create_probe_router()),
            ("", create_metrics_router(registry, METRICS_TOKEN)),
        ],
    )
    # Added last, so it wraps everything already registered: a request rejected
    # by a guard still has to be counted.
    app.add_middleware(MetricsMiddleware, metrics=metrics)
    return app


@pytest.fixture
async def metrics_client(metrics_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=metrics_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def _samples(registry: CollectorRegistry, name: str) -> list[tuple[dict[str, str], float]]:
    return [
        (dict(sample.labels), sample.value)
        for metric in registry.collect()
        for sample in metric.samples
        if sample.name == name
    ]


def test_route_label_uses_the_template_not_the_url() -> None:
    scope = {
        "route": object(),
        "path": "/api/v1/deals/d-42",
        "path_params": {"deal_id": "d-42"},
    }

    assert resolve_route_label(scope) == "/api/v1/deals/:deal_id"


def test_route_label_falls_back_when_nothing_matched() -> None:
    assert resolve_route_label({}) == UNMATCHED_ROUTE_LABEL
    assert resolve_route_label({"path": "/no-such-path"}) == UNMATCHED_ROUTE_LABEL


def test_route_label_substitutes_whole_segments_only() -> None:
    # The id "1" also appears inside a literal segment; only the parameter
    # segment may be replaced.
    scope = {"route": object(), "path": "/v1/items/1", "path_params": {"item_id": "1"}}

    assert resolve_route_label(scope) == "/v1/items/:item_id"


def test_route_label_handles_path_converters() -> None:
    scope = {
        "route": object(),
        "path": "/files/a/b/c.txt",
        "path_params": {"file_path": "a/b/c.txt"},
    }

    assert resolve_route_label(scope) == "/files/:file_path"


def test_route_label_folds_trailing_slashes() -> None:
    assert resolve_route_label({"route": object(), "path": "/items/"}) == "/items"


async def test_requests_are_counted_with_a_bounded_route_label(
    metrics_client: AsyncClient, registry: CollectorRegistry
) -> None:
    await metrics_client.get("/probe/items/1")
    await metrics_client.get("/probe/items/2")

    counted = _samples(registry, "http_requests_total")
    labels = {(item["method"], item["route"], item["status"]): value for item, value in counted}

    # Two different ids collapse onto a single series; that is the whole point.
    assert labels[("GET", "/probe/items/:item_id", "200")] == 2


async def test_latency_is_observed(
    metrics_client: AsyncClient, registry: CollectorRegistry
) -> None:
    await metrics_client.get("/probe/items/1")

    counts = _samples(registry, "http_request_duration_seconds_count")

    assert any(value == 1 for _labels, value in counts)


async def test_unmatched_requests_are_still_counted(
    metrics_client: AsyncClient, registry: CollectorRegistry
) -> None:
    await metrics_client.get("/no-such-path")

    counted = _samples(registry, "http_requests_total")

    assert any(
        item["route"] == UNMATCHED_ROUTE_LABEL and item["status"] == "404"
        for item, _value in counted
    )


async def test_failures_are_counted_as_server_errors(
    metrics_client: AsyncClient, registry: CollectorRegistry
) -> None:
    await metrics_client.get("/probe/boom")

    counted = _samples(registry, "http_requests_total")

    assert any(item["status"] == "500" for item, _value in counted)


async def test_in_flight_gauge_returns_to_zero(
    metrics_client: AsyncClient, registry: CollectorRegistry
) -> None:
    await metrics_client.get("/probe/items/1")

    assert _samples(registry, "http_requests_in_flight") == [({}, 0.0)]


async def test_scrape_requires_the_bearer_token(metrics_client: AsyncClient) -> None:
    anonymous = await metrics_client.get("/metrics")
    wrong = await metrics_client.get("/metrics", headers={"authorization": "Bearer not-the-token"})

    # 404 rather than 401: an unauthorised scraper learns nothing at all.
    assert anonymous.status_code == 404
    assert wrong.status_code == 404


async def test_a_non_ascii_token_is_rejected_like_any_other_wrong_one(
    metrics_client: AsyncClient,
) -> None:
    """A 500 here would confirm the endpoint exists, which is the whole point."""
    # Sent as raw bytes: a server hands the application whatever arrived on the
    # wire, and nothing stops a client from putting non-ASCII in the header.
    response = await metrics_client.get(
        "/metrics", headers={b"authorization": "Bearer пароль-не-той".encode()}
    )

    assert response.status_code == 404


async def test_scrape_returns_the_prometheus_exposition_format(
    metrics_client: AsyncClient,
) -> None:
    await metrics_client.get("/probe/items/1")

    response = await metrics_client.get(
        "/metrics", headers={"authorization": f"Bearer {METRICS_TOKEN}"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == PROMETHEUS_CONTENT_TYPE
    assert response.headers["cache-control"] == "no-store"
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds_bucket" in response.text
    assert "process_uptime_seconds" in response.text


def test_short_tokens_are_refused(registry: CollectorRegistry) -> None:
    with pytest.raises(ValueError, match="at least 16 characters"):
        create_metrics_router(registry, "too-short")


def test_process_metrics_render(registry: CollectorRegistry) -> None:
    register_process_metrics(registry)

    rendered = render_metrics(registry).decode("utf-8")

    assert "# TYPE process_uptime_seconds gauge" in rendered
