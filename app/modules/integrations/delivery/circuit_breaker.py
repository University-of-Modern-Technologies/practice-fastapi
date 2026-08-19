"""Circuit breaker for a single upstream dependency.

State machine
-------------

::

             failures >= threshold
    closed ────────────────────────▶ open
      ▲                               │
      │ success                       │ cool-down elapsed
      │                               ▼
      └──────────────────────────  half-open
               failure ──────────────▶ open

* ``closed``    — every call is allowed. Consecutive transient failures are
  counted; any success resets the counter to zero.
* ``open``      — the dependency is considered down. Calls are refused straight
  away, without a network round-trip, so a struggling service is not hammered
  and callers fail fast instead of piling up on a timeout.
* ``half-open`` — after the cool-down a *single* probe request is admitted. If
  it succeeds the breaker closes and normal traffic resumes; if it fails the
  breaker opens again and a fresh cool-down starts. While the probe is in flight
  all other calls are refused, so recovery is tested with one request, not with
  a thundering herd.

Only *transient* failures (network errors, timeouts, 429, 5xx) are reported as
failures. A 4xx answer proves the service is alive and is reported as a success —
a stream of bad requests from us must never trip the breaker.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from app.modules.integrations.types import CircuitState

__all__ = [
    "DEFAULT_COOLDOWN_MS",
    "DEFAULT_FAILURE_THRESHOLD",
    "CircuitBreaker",
    "CircuitBreakerSnapshot",
    "default_now_ms",
]

#: Consecutive transient failures that open the circuit.
DEFAULT_FAILURE_THRESHOLD = 5
#: How long the circuit stays open before a probe is admitted.
DEFAULT_COOLDOWN_MS = 30_000.0


def default_now_ms() -> float:
    """Wall clock in milliseconds since the epoch.

    Milliseconds rather than seconds because every threshold in this module is
    expressed that way, and one unit throughout is one fewer conversion to get
    wrong.
    """
    return time.time() * 1000.0


@dataclass(frozen=True, slots=True)
class CircuitBreakerSnapshot:
    """What the breaker looks like from outside; read-only by construction."""

    state: CircuitState
    consecutive_failures: int
    last_error_at_ms: float | None
    opened_at_ms: float | None


class CircuitBreaker:
    """Tracks the health of one dependency and refuses calls when it is down."""

    def __init__(
        self,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_ms: float = DEFAULT_COOLDOWN_MS,
        now_ms: Callable[[], float] = default_now_ms,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_ms = cooldown_ms
        self._now_ms = now_ms
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_error_at_ms: float | None = None
        self._opened_at_ms: float | None = None
        self._probe_in_flight = False

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at_ms = self._now_ms()
        self._probe_in_flight = False

    def try_acquire(self) -> bool:
        """True when a call may proceed; admits exactly one probe in half-open."""
        if self._state is CircuitState.OPEN:
            if (
                self._opened_at_ms is None
                or self._now_ms() - self._opened_at_ms < self._cooldown_ms
            ):
                return False
            self._state = CircuitState.HALF_OPEN
            self._probe_in_flight = True
            return True

        if self._state is CircuitState.HALF_OPEN:
            # A probe is already being evaluated; nobody else gets through.
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True

        return True

    def on_success(self) -> None:
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at_ms = None
        self._probe_in_flight = False

    def on_failure(self) -> None:
        self._consecutive_failures += 1
        self._last_error_at_ms = self._now_ms()

        if self._state is CircuitState.HALF_OPEN:
            # The probe failed: back to open with a fresh cool-down.
            self._open()
            return

        if self._consecutive_failures >= self._failure_threshold:
            self._open()

    def snapshot(self) -> CircuitBreakerSnapshot:
        return CircuitBreakerSnapshot(
            state=self._state,
            consecutive_failures=self._consecutive_failures,
            last_error_at_ms=self._last_error_at_ms,
            opened_at_ms=self._opened_at_ms,
        )
