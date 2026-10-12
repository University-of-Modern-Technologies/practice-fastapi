"""The circuit-breaker transport in isolation, decoupled from retries.

Splitting this out of the client's retry loop is what makes these cases
possible to state directly: what the breaker is told about each outcome, and
that it never touches the network once it is open.
"""

from __future__ import annotations

import asyncio

import pytest

from app.modules.integrations.delivery.circuit_breaker import CircuitBreaker
from app.modules.integrations.delivery.transport import (
    DeliveryTransportRequest,
    DeliveryTransportResponse,
)
from app.modules.integrations.delivery.with_circuit_breaker import (
    CircuitBreakerTransport,
    CircuitOpenError,
)
from app.modules.integrations.types import TransportKind

OK = DeliveryTransportResponse(status=200, headers={}, body={"ok": True})
SERVER_ERROR = DeliveryTransportResponse(status=500, headers={}, body={})
CLIENT_ERROR = DeliveryTransportResponse(status=400, headers={}, body={})

REQUEST = DeliveryTransportRequest(method="GET", path="/v1/shipments/1", timeout_ms=1_000)


class FakeTransport:
    kind: TransportKind = TransportKind.HTTP

    def __init__(self, script: list[DeliveryTransportResponse | Exception]) -> None:
        self._script = script
        self.calls = 0

    async def send(self, request: DeliveryTransportRequest) -> DeliveryTransportResponse:  # noqa: ARG002
        entry = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        if isinstance(entry, Exception):
            raise entry
        return entry


async def test_a_successful_response_passes_through_untouched() -> None:
    breaker = CircuitBreaker()
    wrapped = CircuitBreakerTransport(FakeTransport([OK]), breaker)

    assert await wrapped.send(REQUEST) == OK


async def test_a_5xx_is_reported_to_the_breaker_but_still_returned() -> None:
    breaker = CircuitBreaker(failure_threshold=2)
    wrapped = CircuitBreakerTransport(FakeTransport([SERVER_ERROR]), breaker)

    assert await wrapped.send(REQUEST) == SERVER_ERROR
    assert breaker.snapshot().consecutive_failures == 1


async def test_a_4xx_does_not_open_the_breaker() -> None:
    breaker = CircuitBreaker(failure_threshold=1)
    wrapped = CircuitBreakerTransport(FakeTransport([CLIENT_ERROR]), breaker)

    assert await wrapped.send(REQUEST) == CLIENT_ERROR
    snapshot = breaker.snapshot()
    assert snapshot.state.value == "closed"
    assert snapshot.consecutive_failures == 0


async def test_an_open_breaker_short_circuits_without_touching_the_transport() -> None:
    breaker = CircuitBreaker(failure_threshold=1)
    transport = FakeTransport([SERVER_ERROR])
    wrapped = CircuitBreakerTransport(transport, breaker)

    await wrapped.send(REQUEST)
    assert breaker.snapshot().state.value == "open"

    calls_before = transport.calls
    with pytest.raises(CircuitOpenError):
        await wrapped.send(REQUEST)
    assert transport.calls == calls_before


async def test_a_network_failure_is_reported_to_the_breaker_and_reraised() -> None:
    breaker = CircuitBreaker(failure_threshold=5)
    wrapped = CircuitBreakerTransport(FakeTransport([ConnectionResetError("boom")]), breaker)

    with pytest.raises(ConnectionResetError):
        await wrapped.send(REQUEST)
    assert breaker.snapshot().consecutive_failures == 1


def test_kind_mirrors_the_wrapped_transport() -> None:
    wrapped = CircuitBreakerTransport(FakeTransport([OK]), CircuitBreaker())
    assert wrapped.kind is TransportKind.HTTP


# --- regressions ----------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
async def test_a_refusal_of_our_credentials_counts_against_the_breaker(status: int) -> None:
    breaker = CircuitBreaker(failure_threshold=2)
    refused = DeliveryTransportResponse(status=status, headers={}, body={})
    wrapped = CircuitBreakerTransport(FakeTransport([refused]), breaker)

    await wrapped.send(REQUEST)
    await wrapped.send(REQUEST)

    assert breaker.snapshot().state == "open"


class GatedTransport:
    """Holds every call until the test lets it answer."""

    kind: TransportKind = TransportKind.HTTP

    def __init__(self) -> None:
        self.gate: asyncio.Future[DeliveryTransportResponse] = (
            asyncio.get_running_loop().create_future()
        )

    async def send(self, request: DeliveryTransportRequest) -> DeliveryTransportResponse:  # noqa: ARG002
        return await self.gate


async def test_a_late_success_does_not_close_an_open_circuit() -> None:
    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=1, cooldown_ms=1_000, now_ms=lambda: now[0])
    slow = GatedTransport()
    pending = asyncio.ensure_future(CircuitBreakerTransport(slow, breaker).send(REQUEST))
    await asyncio.sleep(0)

    # Another call opens the circuit while the first is still in flight.
    await CircuitBreakerTransport(FakeTransport([SERVER_ERROR]), breaker).send(REQUEST)
    assert breaker.snapshot().state == "open"

    slow.gate.set_result(OK)
    await pending

    assert breaker.snapshot().state == "open"
    now[0] = 500.0
    assert breaker.try_acquire() is False


async def test_a_cancelled_probe_gives_its_slot_back() -> None:
    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=1, cooldown_ms=1_000, now_ms=lambda: now[0])
    breaker.on_failure()
    now[0] = 1_000.0

    probe = asyncio.ensure_future(CircuitBreakerTransport(GatedTransport(), breaker).send(REQUEST))
    await asyncio.sleep(0)
    assert breaker.snapshot().state == "half-open"
    probe.cancel()
    with pytest.raises(asyncio.CancelledError):
        await probe

    # Without the slot back, the half-open circuit would refuse everything.
    assert breaker.try_acquire() is True
