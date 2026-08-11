"""Composes several readiness probes into one.

The result satisfies the very `ReadinessCheck` shape it is built from, so
`readiness_checks` cannot tell it apart from a plain probe: a `database`
entry can become "connection reachable" plus "schema applied" without the
router — or the cross-contract test pinning the response shape — noticing
anything changed.
"""

from __future__ import annotations

from app.health.readiness import (
    DEFAULT_CHECK_TIMEOUT_SECONDS,
    ReadinessCheck,
    ReadinessCheckResult,
    is_ready,
    run_readiness_checks,
)


class CompositeReadinessError(Exception):
    """Raised when a composite's own probe fails.

    Carries the sub-results for the log line only: the router already keeps
    every check's cause out of the HTTP response, so nesting the detail here
    never reaches an unauthenticated caller.
    """

    def __init__(self, name: str, results: list[ReadinessCheckResult]) -> None:
        failed = ", ".join(
            f"{result.name}: {result.status}"
            for result in results
            if result.status != "up" and result.critical
        )
        super().__init__(f'Composite readiness check "{name}" failed: {failed}')
        self.results = results


def create_composite_readiness_check(
    name: str,
    checks: list[ReadinessCheck],
    *,
    sub_check_timeout_seconds: float = DEFAULT_CHECK_TIMEOUT_SECONDS,
    timeout_seconds: float | None = None,
) -> ReadinessCheck:
    """Folds several dependency probes into one readiness entry.

    Sub-checks keep their own timeout and run concurrently, exactly like the
    top-level probe list, so one hanging dependency inside the composite still
    cannot delay a sibling sub-check or the rest of the outer probe.
    """
    # A composite is only as safe as its riskiest part: if any sub-check is
    # declared critical, a failure there must still take the instance out of
    # rotation, exactly as it would if that sub-check were registered on its
    # own at the top level.
    critical = any(entry.critical for entry in checks)

    async def check() -> None:
        results = await run_readiness_checks(checks, sub_check_timeout_seconds)
        if not is_ready(results):
            raise CompositeReadinessError(name, results)

    return ReadinessCheck(
        name=name, check=check, critical=critical, timeout_seconds=timeout_seconds
    )
