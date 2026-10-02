"""Health endpoints.

* ``GET /health/live``    — process liveness, no I/O, always cheap.
* ``GET /health/startup`` — has the bootstrap finished? Use as a startup probe.
* ``GET /health/ready``   — dependency readiness; 200 only when every critical
                            check passes and the process is not draining.
* ``GET /health/info``    — non-sensitive build and runtime metadata.
"""

from __future__ import annotations

import time
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.core.settings import Settings
from app.health.lifecycle import ServiceLifecycle, service_lifecycle
from app.health.readiness import (
    DEFAULT_CHECK_TIMEOUT_SECONDS,
    ReadinessCheck,
    ReadinessCheckResult,
    is_degraded,
    is_ready,
    run_readiness_checks,
)

logger = get_logger("health")

_PROCESS_STARTED_AT = time.monotonic()

SERVICE_NAME = "practice-crm-python-backend"

#: Last resort: neither installed metadata nor the project file was readable.
_UNKNOWN_VERSION = "0.0.0"

#: `app/health/routes.py` → project root.
_PROJECT_FILE = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _version_from_project_file() -> str | None:
    """Reads the version straight from the project file.

    The application is run from a source tree rather than installed, so there is
    usually no distribution to interrogate; the project file is then the only
    place the version is declared.
    """
    try:
        with _PROJECT_FILE.open("rb") as handle:
            declared = tomllib.load(handle).get("project", {}).get("version")
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return declared if isinstance(declared, str) else None


def _read_version() -> str:
    """Resolves the running version instead of repeating it as a constant.

    A hardcoded constant drifts from the packaging metadata the moment one of
    the two is bumped, and a stale version in ``/health/info`` is worse than no
    version at all: it makes a deployment look like a build it is not.
    """
    try:
        return metadata.version(SERVICE_NAME)
    except metadata.PackageNotFoundError:
        return _version_from_project_file() or _UNKNOWN_VERSION


SERVICE_VERSION = _read_version()


def _to_public(result: ReadinessCheckResult) -> dict[str, Any]:
    """Public per-check payload: never carries the failure cause."""
    return {
        "name": result.name,
        "status": result.status,
        "durationMs": result.duration_ms,
        "critical": result.critical,
    }


def _log_failures(results: list[ReadinessCheckResult]) -> None:
    for result in results:
        if result.status == "up":
            continue
        logger.error(
            "Readiness check failed",
            check=result.name,
            status=result.status,
            durationMs=result.duration_ms,
            critical=result.critical,
            error=repr(result.error),
        )


def create_health_router(
    settings: Settings,
    readiness_checks: list[ReadinessCheck] | None = None,
    *,
    lifecycle: ServiceLifecycle | None = None,
    check_timeout_seconds: float = DEFAULT_CHECK_TIMEOUT_SECONDS,
) -> APIRouter:
    router = APIRouter(tags=["Health"])
    checks = readiness_checks or []
    phase_source = lifecycle or service_lifecycle

    @router.get("/live", summary="Liveness probe")
    async def live() -> dict[str, str]:
        # Liveness stays successful while draining: the process is healthy, it
        # is simply no longer accepting new traffic — that is what readiness says.
        return {"status": "ok"}

    # Kept out of the published schema: an orchestrator probe is not part of the
    # API contract a client codes against.
    @router.get("/startup", summary="Startup probe", include_in_schema=False)
    async def startup() -> JSONResponse:
        has_started = phase_source.has_started
        return JSONResponse(
            status_code=200 if has_started else 503,
            content={
                "status": "started" if has_started else "starting",
                "phase": phase_source.phase,
            },
        )

    # The 503 body is the probe report, not the error envelope.
    @router.get(
        "/ready",
        summary="Readiness probe",
        responses={503: {"description": "Одна або кілька залежностей недоступні"}},  # noqa: RUF001
    )
    async def ready() -> JSONResponse:
        if not phase_source.is_accepting_traffic:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready" if phase_source.phase == "starting" else "draining",
                    "phase": phase_source.phase,
                    "checks": [],
                },
            )

        results = await run_readiness_checks(checks, check_timeout_seconds)
        _log_failures(results)

        ready_now = is_ready(results)
        if not ready_now:
            status = "not_ready"
        elif is_degraded(results):
            status = "degraded"
        else:
            status = "ready"

        return JSONResponse(
            status_code=200 if ready_now else 503,
            content={
                "status": status,
                "phase": phase_source.phase,
                "checks": [_to_public(result) for result in results],
            },
        )

    @router.get("/info", summary="Build and runtime metadata", include_in_schema=False)
    async def info() -> dict[str, Any]:
        return {
            "name": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "nodeEnv": settings.app_env,
            "phase": phase_source.phase,
            "uptimeSeconds": round(time.monotonic() - _PROCESS_STARTED_AT),
        }

    return router
