"""The breaker's state machine, driven by a clock the test owns."""

from __future__ import annotations

import pytest

from app.modules.integrations.delivery.circuit_breaker import CircuitBreaker
from app.modules.integrations.types import CircuitState


class FakeClock:
    """A clock that only moves when the test says so."""

    def __init__(self, start_ms: float = 0.0) -> None:
        self.now_ms = start_ms

    def __call__(self) -> float:
        return self.now_ms

    def advance(self, milliseconds: float) -> None:
        self.now_ms += milliseconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def test_a_closed_breaker_admits_every_call(clock: FakeClock) -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_ms=1_000, now_ms=clock)

    assert breaker.try_acquire() is True
    assert breaker.try_acquire() is True
    assert breaker.snapshot().state is CircuitState.CLOSED


def test_the_circuit_opens_only_on_the_threshold_failure(clock: FakeClock) -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_ms=1_000, now_ms=clock)

    breaker.on_failure()
    breaker.on_failure()
    assert breaker.snapshot().state is CircuitState.CLOSED

    breaker.on_failure()
    snapshot = breaker.snapshot()
    assert snapshot.state is CircuitState.OPEN
    assert snapshot.consecutive_failures == 3
    assert breaker.try_acquire() is False


def test_a_success_forgives_the_failures_counted_so_far(clock: FakeClock) -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_ms=1_000, now_ms=clock)

    breaker.on_failure()
    breaker.on_success()
    breaker.on_failure()

    assert breaker.snapshot().state is CircuitState.CLOSED
    assert breaker.snapshot().consecutive_failures == 1


def test_the_cool_down_has_to_elapse_before_a_probe_is_admitted(clock: FakeClock) -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_ms=10_000, now_ms=clock)
    breaker.on_failure()

    clock.advance(9_999)
    assert breaker.try_acquire() is False
    assert breaker.snapshot().state is CircuitState.OPEN

    clock.advance(1)
    assert breaker.try_acquire() is True
    assert breaker.snapshot().state is CircuitState.HALF_OPEN


def test_exactly_one_probe_is_admitted_while_half_open(clock: FakeClock) -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_ms=10_000, now_ms=clock)
    breaker.on_failure()
    clock.advance(10_000)

    assert breaker.try_acquire() is True
    # Recovery is tested with one request, not with a thundering herd.
    assert breaker.try_acquire() is False


def test_a_successful_probe_closes_the_circuit(clock: FakeClock) -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_ms=10_000, now_ms=clock)
    breaker.on_failure()
    clock.advance(10_000)
    breaker.try_acquire()

    breaker.on_success()

    snapshot = breaker.snapshot()
    assert snapshot.state is CircuitState.CLOSED
    assert snapshot.consecutive_failures == 0
    assert snapshot.opened_at_ms is None
    assert breaker.try_acquire() is True


def test_a_failed_probe_reopens_the_circuit_with_a_fresh_cool_down(clock: FakeClock) -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_ms=10_000, now_ms=clock)
    breaker.on_failure()
    clock.advance(10_000)
    breaker.try_acquire()

    breaker.on_failure()

    snapshot = breaker.snapshot()
    assert snapshot.state is CircuitState.OPEN
    assert snapshot.opened_at_ms == 10_000
    assert breaker.try_acquire() is False

    clock.advance(9_999)
    assert breaker.try_acquire() is False
    clock.advance(1)
    assert breaker.try_acquire() is True


def test_the_snapshot_records_when_the_last_failure_happened(clock: FakeClock) -> None:
    breaker = CircuitBreaker(failure_threshold=5, cooldown_ms=1_000, now_ms=clock)
    assert breaker.snapshot().last_error_at_ms is None

    clock.advance(4_200)
    breaker.on_failure()

    assert breaker.snapshot().last_error_at_ms == 4_200
    assert breaker.snapshot().opened_at_ms is None
