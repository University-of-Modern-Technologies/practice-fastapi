"""The probes answer with exactly the bodies the description publishes.

The readiness handler writes its body by hand so the status code can follow the
verdict, which means nothing ties that body to the model the description shows.
These tests do: every outcome the probe can report is read back through the
published model, and must come out unchanged.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.core.settings import Settings
from app.factory import create_app
from app.health.lifecycle import service_lifecycle
from app.health.readiness import ReadinessCheck
from app.health.routes import LivenessReport, ReadinessReport


async def _passing() -> None:
    return None


async def _failing() -> None:
    message = "dependency is unreachable"
    raise ConnectionError(message)


def _round_trip(model: type[BaseModel], body: dict[str, Any]) -> dict[str, Any]:
    return model.model_validate(body).model_dump(mode="json", by_alias=True)


async def _get(app: FastAPI, path: str) -> tuple[int, dict[str, Any]]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as probe:
        response = await probe.get(path)
    return response.status_code, response.json()


async def test_the_liveness_body_is_the_published_one(settings: Settings) -> None:
    status, body = await _get(create_app(settings), "/api/health/live")

    assert status == 200
    assert _round_trip(LivenessReport, body) == body


@pytest.mark.parametrize(
    ("checks", "expected_status", "expected_report"),
    [
        ([], 200, "ready"),
        ([("database", _passing, True)], 200, "ready"),
        ([("database", _passing, True), ("cache", _failing, False)], 200, "degraded"),
        ([("database", _failing, True)], 503, "not_ready"),
    ],
)
async def test_every_readiness_verdict_has_the_published_body(
    settings: Settings,
    checks: list[tuple[str, Callable[[], Awaitable[None]], bool]],
    expected_status: int,
    expected_report: str,
) -> None:
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    app = create_app(
        settings,
        readiness_checks=[
            ReadinessCheck(name=name, check=check, critical=critical)
            for name, check, critical in checks
        ],
    )

    status, body = await _get(app, "/api/health/ready")

    assert status == expected_status
    assert body["status"] == expected_report
    assert _round_trip(ReadinessReport, body) == body


@pytest.mark.parametrize(("drain", "expected_report"), [(False, "not_ready"), (True, "draining")])
async def test_a_refusal_outside_the_serving_phase_has_the_published_body(
    settings: Settings, *, drain: bool, expected_report: str
) -> None:
    service_lifecycle.reset()
    if drain:
        service_lifecycle.mark_started()
        service_lifecycle.begin_draining()

    status, body = await _get(create_app(settings), "/api/health/ready")

    assert status == 503
    assert body["status"] == expected_report
    assert _round_trip(ReadinessReport, body) == body
