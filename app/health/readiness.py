"""Readiness probe execution.

Every registered dependency check runs concurrently behind its own timeout, so a
single hanging dependency can never hold the probe open. Failure causes are
returned for logging only; the HTTP response exposes nothing but the status and
the duration.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

DEFAULT_CHECK_TIMEOUT_SECONDS = 2.0

ReadinessStatus = Literal["up", "down", "timed_out"]


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    """A single dependency probe."""

    #: Stable identifier reported in the payload, e.g. ``database``.
    name: str
    #: Returns normally when the dependency is healthy, raises otherwise.
    check: Callable[[], Awaitable[None]]
    #: When false, a failure degrades the report but still yields HTTP 200.
    critical: bool = True
    #: Per-check timeout overriding the router default.
    timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ReadinessCheckResult:
    name: str
    status: ReadinessStatus
    duration_ms: float
    critical: bool
    #: Kept out of the HTTP response and used for logging only.
    error: BaseException | None = field(default=None)


async def _run_single(
    entry: ReadinessCheck,
    default_timeout_seconds: float,
) -> ReadinessCheckResult:
    # Explicitly `None`, not falsy: a check configured with a zero timeout asked
    # for a zero timeout, and silently replacing it with the default would let a
    # check that must never block run for the full default instead.
    timeout = default_timeout_seconds if entry.timeout_seconds is None else entry.timeout_seconds
    started_at = time.perf_counter()

    try:
        async with asyncio.timeout(timeout):
            await entry.check()
    except TimeoutError as error:
        return ReadinessCheckResult(
            entry.name,
            "timed_out",
            round((time.perf_counter() - started_at) * 1000, 2),
            entry.critical,
            error,
        )
    except Exception as error:  # a probe must never propagate a dependency failure
        return ReadinessCheckResult(
            entry.name,
            "down",
            round((time.perf_counter() - started_at) * 1000, 2),
            entry.critical,
            error,
        )

    return ReadinessCheckResult(
        entry.name,
        "up",
        round((time.perf_counter() - started_at) * 1000, 2),
        entry.critical,
    )


async def run_readiness_checks(
    checks: list[ReadinessCheck],
    default_timeout_seconds: float = DEFAULT_CHECK_TIMEOUT_SECONDS,
) -> list[ReadinessCheckResult]:
    """Runs all checks concurrently, isolating failures and timeouts."""
    if not checks:
        return []
    return list(
        await asyncio.gather(*(_run_single(entry, default_timeout_seconds) for entry in checks))
    )


def is_ready(results: list[ReadinessCheckResult]) -> bool:
    """A report is ready when no critical dependency failed."""
    return all(result.status == "up" or not result.critical for result in results)


def is_degraded(results: list[ReadinessCheckResult]) -> bool:
    """True when a non-critical dependency failed while the service stays ready."""
    return any(result.status != "up" and not result.critical for result in results)
