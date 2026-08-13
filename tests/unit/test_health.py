from __future__ import annotations

import asyncio
import tomllib
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.settings import Settings
from app.factory import create_app
from app.health.lifecycle import ServiceLifecycle, service_lifecycle
from app.health.readiness import ReadinessCheck, is_degraded, is_ready, run_readiness_checks


def _declared_version() -> str:
    """The one place the version is written down, read independently of the app."""
    project_file = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with project_file.open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    assert isinstance(version, str)
    return version


async def test_liveness_needs_no_dependencies(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_reports_ready_without_checks(client: AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


async def test_readiness_fails_while_draining(client: AsyncClient) -> None:
    service_lifecycle.begin_draining()

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "draining"


async def test_info_exposes_no_secrets(client: AsyncClient) -> None:
    body = (await client.get("/health/info")).json()

    assert set(body) == {"name", "version", "nodeEnv", "phase", "uptimeSeconds"}
    # The service name matches the distribution, and the version is read from
    # its metadata rather than repeated as a constant that can drift.
    assert body["name"] == "practice-crm-python-backend"
    assert body["version"] == _declared_version()


async def test_the_probes_stay_out_of_the_published_schema(client: AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]

    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/health/startup" not in paths
    assert "/health/info" not in paths
    assert paths["/health/live"]["get"]["tags"] == ["Health"]


async def test_failing_critical_check_takes_the_instance_out_of_rotation(
    settings: Settings,
) -> None:
    async def failing() -> None:
        message = "database is unreachable"
        raise ConnectionError(message)

    app: FastAPI = create_app(
        settings,
        readiness_checks=[ReadinessCheck(name="database", check=failing)],
    )
    service_lifecycle.reset()
    service_lifecycle.mark_started()

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as probe:
        response = await probe.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    # The cause is logged, never published.
    assert body["checks"][0] == {
        "name": "database",
        "status": "down",
        "durationMs": pytest.approx(body["checks"][0]["durationMs"]),
        "critical": True,
    }


async def test_non_critical_failure_only_degrades() -> None:
    async def failing() -> None:
        message = "cache is unreachable"
        raise ConnectionError(message)

    results = await run_readiness_checks(
        [ReadinessCheck(name="cache", check=failing, critical=False)]
    )

    assert is_ready(results)
    assert is_degraded(results)


async def test_a_hanging_check_times_out_instead_of_blocking() -> None:
    async def hanging() -> None:
        await asyncio.sleep(10)

    results = await run_readiness_checks(
        [ReadinessCheck(name="slow", check=hanging, timeout_seconds=0.05)]
    )

    assert results[0].status == "timed_out"


async def test_a_zero_timeout_is_honoured_rather_than_replaced_by_the_default() -> None:
    """Zero is a configured value, not a missing one."""

    async def hanging() -> None:
        await asyncio.sleep(10)

    results = await run_readiness_checks(
        [ReadinessCheck(name="instant", check=hanging, timeout_seconds=0)],
        default_timeout_seconds=10,
    )

    assert results[0].status == "timed_out"


def test_draining_is_terminal() -> None:
    lifecycle = ServiceLifecycle()
    lifecycle.mark_started()
    lifecycle.begin_draining()

    lifecycle.mark_started()

    assert lifecycle.phase == "draining"
    assert not lifecycle.is_accepting_traffic
