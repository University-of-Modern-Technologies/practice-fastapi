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

Only failures of the dependency (network errors, timeouts, 429, 5xx, and a
refusal of our credentials) are reported as failures. Any other 4xx answer proves
the service is alive and is reported as a success — a stream of bad requests
from us must never trip the breaker.

Every admitted call carries a permit naming the period it was admitted in.
Opening the circuit starts a new period, so a call that was already in flight
when the circuit opened reports into a period that is over: its result is
ignored instead of closing the circuit, or extending it, behind the probe's
back. A call that never reports at all — cancelled on its way — gives its permit
back, so an abandoned probe cannot leave the circuit refusing everything.
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
    "CircuitPermit",
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


@dataclass(frozen=True, slots=True)
class CircuitPermit:
    """What an admitted call reports back with."""

    #: The period the call was admitted in; a new one starts each time it opens.
    generation: int
    #: Whether this is the single call admitted to test a half-open circuit.
    probe: bool


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
        self._generation = 0

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at_ms = self._now_ms()
        self._probe_in_flight = False
        self._generation += 1

    def _is_late(self, permit: CircuitPermit | None) -> bool:
        """A result from a period that is over changes nothing."""
        return permit is not None and permit.generation != self._generation

    def acquire(self) -> CircuitPermit | None:
        """A permit when a call may proceed, ``None`` when it is refused."""
        if self._state is CircuitState.OPEN:
            if (
                self._opened_at_ms is None
                or self._now_ms() - self._opened_at_ms < self._cooldown_ms
            ):
                return None
            self._state = CircuitState.HALF_OPEN
            self._probe_in_flight = True
            return CircuitPermit(self._generation, probe=True)

        if self._state is CircuitState.HALF_OPEN:
            # A probe is already being evaluated; nobody else gets through.
            if self._probe_in_flight:
                return None
            self._probe_in_flight = True
            return CircuitPermit(self._generation, probe=True)

        return CircuitPermit(self._generation, probe=False)

    def try_acquire(self) -> bool:
        """True when a call may proceed; admits exactly one probe in half-open."""
        return self.acquire() is not None

    def release(self, permit: CircuitPermit) -> None:
        """Gives back a permit whose call ended without an outcome.

        A probe that is cancelled never reports success or failure; unless its
        slot is freed, the half-open circuit would wait for it forever and
        refuse every call in the meantime.
        """
        if permit.probe and not self._is_late(permit) and self._state is CircuitState.HALF_OPEN:
            self._probe_in_flight = False

    def on_success(self, permit: CircuitPermit | None = None) -> None:
        """Without a permit the result is taken to belong to the current period."""
        if self._is_late(permit):
            return
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at_ms = None
        self._probe_in_flight = False

    def on_failure(self, permit: CircuitPermit | None = None) -> None:
        if self._is_late(permit):
            return
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
