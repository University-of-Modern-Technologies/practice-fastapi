"""The retry transport in isolation, decoupled from the circuit breaker.

These cases are the whole point of splitting the client's old all-in-one loop
apart: idempotency, backoff and `Retry-After` can now be asserted without any
of them being entangled with breaker bookkeeping. The one composition test at
the bottom checks that the two layers still cooperate correctly when stacked.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.errors import AppError
from app.modules.integrations.delivery.circuit_breaker import CircuitBreaker
from app.modules.integrations.delivery.errors import (
    DELIVERY_REJECTED,
    DELIVERY_TIMEOUT,
    DELIVERY_UNAVAILABLE,
)
from app.modules.integrations.delivery.retry import RetryingTransport, RetryOptions
from app.modules.integrations.delivery.transport import (
    DeliveryTransportRequest,
    DeliveryTransportResponse,
    HttpDeliveryTransport,
    TransportTimeoutError,
)
from app.modules.integrations.delivery.with_circuit_breaker import CircuitBreakerTransport
from app.modules.integrations.types import TransportKind


def ok() -> DeliveryTransportResponse:
    return DeliveryTransportResponse(status=200, headers={}, body={})


def status(code: int, headers: dict[str, str] | None = None) -> DeliveryTransportResponse:
    return DeliveryTransportResponse(status=code, headers=headers or {}, body={})


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


class DelayRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, milliseconds: float) -> None:
        self.calls.append(milliseconds)


def request(*, idempotent: bool) -> DeliveryTransportRequest:
    return DeliveryTransportRequest(method="GET", path="/v1/shipments/1", idempotent=idempotent)


async def code_of(call: Any) -> str:
    try:
        await call
    except AppError as error:
        return error.code
    message = "Expected the call to fail"
    raise AssertionError(message)


async def test_a_non_idempotent_request_is_sent_exactly_once_even_after_a_timeout() -> None:
    delay = DelayRecorder()
    transport = FakeTransport([TransportTimeoutError("timed out"), ok()])
    wrapped = RetryingTransport(
        transport, RetryOptions(delay=delay, random=lambda: 1.0, max_attempts=3)
    )

    assert await code_of(wrapped.send(request(idempotent=False))) == DELIVERY_TIMEOUT
    assert transport.calls == 1
    assert delay.calls == []


async def test_an_idempotent_request_is_retried_on_a_transient_status_until_it_succeeds() -> None:
    delay = DelayRecorder()
    transport = FakeTransport([status(503), status(500), ok()])
    wrapped = RetryingTransport(
        transport,
        RetryOptions(
            delay=delay,
            random=lambda: 1.0,
            max_attempts=3,
            base_backoff_ms=100,
            max_backoff_ms=1_000,
        ),
    )

    response = await wrapped.send(request(idempotent=True))

    assert response.status == 200
    assert transport.calls == 3
    assert delay.calls == [100, 200]


async def test_a_4xx_is_translated_to_delivery_rejected_without_a_retry() -> None:
    delay = DelayRecorder()
    transport = FakeTransport([status(404)])
    wrapped = RetryingTransport(transport, RetryOptions(delay=delay, max_attempts=3))

    assert await code_of(wrapped.send(request(idempotent=True))) == DELIVERY_REJECTED
    assert transport.calls == 1
    assert delay.calls == []


async def test_an_unreasonable_retry_after_fails_fast() -> None:
    delay = DelayRecorder()
    transport = FakeTransport([status(503, {"retry-after": "600"})])
    wrapped = RetryingTransport(
        transport, RetryOptions(delay=delay, max_attempts=3, max_retry_after_ms=10_000)
    )

    assert await code_of(wrapped.send(request(idempotent=True))) == DELIVERY_UNAVAILABLE
    assert delay.calls == []


async def test_the_circuit_breaker_sees_every_attempt_not_just_the_first() -> None:
    # Two transient failures against a threshold of 2 must open the breaker
    # before a third attempt can even reach the transport — which is only
    # true if the breaker is consulted on every retry, not just the first.
    delay = DelayRecorder()
    transport = FakeTransport([status(500), status(500), ok()])
    breaker = CircuitBreaker(failure_threshold=2)
    wrapped = RetryingTransport(
        CircuitBreakerTransport(transport, breaker),
        RetryOptions(
            delay=delay, random=lambda: 1.0, max_attempts=3, base_backoff_ms=1, max_backoff_ms=1
        ),
    )

    assert await code_of(wrapped.send(request(idempotent=True))) == DELIVERY_UNAVAILABLE
    assert transport.calls == 2
    assert breaker.snapshot().state.value == "open"


@pytest.mark.parametrize("code", [401, 403])
async def test_a_refusal_of_our_credentials_is_unavailable_and_not_retried(code: int) -> None:
    transport = FakeTransport([status(code), ok()])
    wrapped = RetryingTransport(transport, RetryOptions(delay=DelayRecorder(), max_attempts=3))

    with pytest.raises(AppError) as failure:
        await wrapped.send(request(idempotent=True))

    assert failure.value.status_code == 503
    assert failure.value.code == DELIVERY_UNAVAILABLE
    assert transport.calls == 1


async def test_the_http_transport_holds_one_deadline_for_the_whole_round_trip() -> None:
    class TricklingClient:
        """Answers within each phase's own timeout but never finishes."""

        async def request(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
            await asyncio.sleep(5)

    transport = HttpDeliveryTransport(
        base_url="https://carrier.invalid",
        client=TricklingClient(),  # type: ignore[arg-type]
    )
    timed = DeliveryTransportRequest(method="GET", path="/v1/shipments/1", timeout_ms=20)

    with pytest.raises(TransportTimeoutError):
        await asyncio.wait_for(transport.send(timed), timeout=2)
