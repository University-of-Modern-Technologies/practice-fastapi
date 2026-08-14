"""How the delivery client behaves when the upstream misbehaves.

Every source of non-determinism — the clock, the jitter, the sleep — is injected,
so a retry policy that would otherwise take seconds of real waiting to observe is
asserted exactly, in microseconds.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.errors import AppError
from app.modules.integrations.delivery.client import (
    DeliveryClient,
    DeliveryClientOptions,
    parse_retry_after_ms,
)
from app.modules.integrations.delivery.errors import (
    DELIVERY_INVALID_RESPONSE,
    DELIVERY_REJECTED,
    DELIVERY_TIMEOUT,
    DELIVERY_UNAVAILABLE,
)
from app.modules.integrations.delivery.transport import (
    DeliveryTransportRequest,
    DeliveryTransportResponse,
    HttpDeliveryTransport,
    TransportTimeoutError,
)
from app.modules.integrations.schemas import CreateShipmentRequest, QuoteRequest
from app.modules.integrations.types import CircuitState, TransportKind

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
START_MS = EPOCH.timestamp() * 1000.0

VALID_QUOTE: dict[str, Any] = {
    "quote_id": "qte_1",
    "carrier": "Test Carrier",
    "service": "standard",
    "amount": "12.50",
    "currency": "eur",
    "estimated_days": 3,
    "expires_at": "2026-01-01T00:00:00.000Z",
}

VALID_SHIPMENT: dict[str, Any] = {
    "shipment_id": "shp_1",
    "order_id": "ord_1",
    "status": "CREATED",
    "carrier": "Test Carrier",
    "tracking_number": "TRK1",
    "created_at": "2026-01-01T00:00:00.000Z",
    "estimated_delivery_at": None,
}

QUOTE_REQUEST = QuoteRequest.model_validate(
    {
        "orderId": "ord_1",
        "origin": {"country": "PL", "city": "Warsaw", "postalCode": "00-001", "line1": "Street 1"},
        "destination": {
            "country": "DE",
            "city": "Berlin",
            "postalCode": "10115",
            "line1": "Street 2",
        },
        "parcel": {"weightGrams": 1_000, "lengthCm": 10, "widthCm": 10, "heightCm": 10},
    }
)

SHIPMENT_REQUEST = CreateShipmentRequest.model_validate(
    {
        "quoteId": "qte_1",
        "orderId": "ord_1",
        "destination": QUOTE_REQUEST.destination.model_dump(by_alias=True),
        "parcel": QUOTE_REQUEST.parcel.model_dump(by_alias=True),
    }
)


def ok(body: Any) -> DeliveryTransportResponse:
    return DeliveryTransportResponse(status=200, headers={}, body=body)


def status(code: int, headers: dict[str, str] | None = None) -> DeliveryTransportResponse:
    return DeliveryTransportResponse(
        status=code, headers=headers or {}, body={"error": "upstream detail"}
    )


class FakeTransport:
    """Replays a scripted sequence; an exception entry is raised, not returned."""

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


class FakeClock:
    def __init__(self) -> None:
        self.now_ms = START_MS

    def __call__(self) -> float:
        return self.now_ms

    def advance(self, milliseconds: float) -> None:
        self.now_ms += milliseconds


class DelayRecorder:
    """Stands in for sleeping: records the request, returns immediately."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, milliseconds: float) -> None:
        self.calls.append(milliseconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def delay() -> DelayRecorder:
    return DelayRecorder()


@pytest.fixture
def build_client(clock: FakeClock, delay: DelayRecorder) -> Callable[..., DeliveryClient]:
    def factory(transport: Any, **overrides: Any) -> DeliveryClient:
        options = DeliveryClientOptions(
            transport=transport,
            delay=delay,
            now_ms=clock,
            # Fixed jitter keeps the asserted backoff values deterministic.
            random=lambda: 1.0,
            base_backoff_ms=100,
            max_backoff_ms=1_000,
        )
        return DeliveryClient(replace(options, **overrides))

    return factory


async def code_of(call: Awaitable[Any]) -> str:
    try:
        await call
    except AppError as error:
        return error.code
    message = "Expected the call to fail"
    raise AssertionError(message)


async def test_an_idempotent_call_is_retried_on_5xx_and_succeeds(
    build_client: Callable[..., DeliveryClient], delay: DelayRecorder
) -> None:
    transport = FakeTransport([status(503), status(500), ok(VALID_QUOTE)])
    client = build_client(transport)

    quote = await client.request_quote(QUOTE_REQUEST)

    assert quote.quote_id == "qte_1"
    assert quote.currency == "EUR"
    assert transport.calls == 3
    # Full jitter with ``random() == 1`` gives the whole exponential window.
    assert delay.calls == [100, 200]


async def test_a_client_error_is_reported_as_rejected_and_never_retried(
    build_client: Callable[..., DeliveryClient], delay: DelayRecorder
) -> None:
    transport = FakeTransport([status(400)])
    client = build_client(transport)

    assert await code_of(client.request_quote(QUOTE_REQUEST)) == DELIVERY_REJECTED
    assert transport.calls == 1
    assert delay.calls == []


async def test_the_upstream_body_never_reaches_the_caller(
    build_client: Callable[..., DeliveryClient],
) -> None:
    client = build_client(FakeTransport([status(400)]))

    with pytest.raises(AppError) as caught:
        await client.request_quote(QUOTE_REQUEST)

    assert caught.value.status_code == 422
    assert caught.value.message == "The delivery service rejected the request"
    assert caught.value.details is None


async def test_an_upstream_404_stays_a_404(build_client: Callable[..., DeliveryClient]) -> None:
    client = build_client(FakeTransport([status(404)]))

    with pytest.raises(AppError) as caught:
        await client.get_shipment("missing")

    assert caught.value.status_code == 404
    assert caught.value.code == DELIVERY_REJECTED


async def test_an_exhausted_timeout_becomes_delivery_timeout(
    build_client: Callable[..., DeliveryClient],
) -> None:
    transport = FakeTransport([TransportTimeoutError("timed out")])
    client = build_client(transport)

    assert await code_of(client.request_quote(QUOTE_REQUEST)) == DELIVERY_TIMEOUT
    assert transport.calls == 3


async def test_a_non_idempotent_call_is_not_replayed_after_a_timeout(
    build_client: Callable[..., DeliveryClient],
) -> None:
    transport = FakeTransport([TransportTimeoutError("timed out"), ok(VALID_SHIPMENT)])
    client = build_client(transport)

    assert await code_of(client.create_shipment(SHIPMENT_REQUEST)) == DELIVERY_TIMEOUT
    # Replaying a shipment creation could dispatch the parcel twice.
    assert transport.calls == 1


async def test_a_network_error_becomes_delivery_unavailable(
    build_client: Callable[..., DeliveryClient],
) -> None:
    client = build_client(FakeTransport([ConnectionResetError("ECONNRESET")]), max_attempts=1)

    assert await code_of(client.request_quote(QUOTE_REQUEST)) == DELIVERY_UNAVAILABLE


async def test_retry_after_is_obeyed_to_the_second(
    build_client: Callable[..., DeliveryClient], delay: DelayRecorder
) -> None:
    transport = FakeTransport([status(429, {"retry-after": "2"}), ok(VALID_QUOTE)])
    client = build_client(transport)

    await client.request_quote(QUOTE_REQUEST)

    assert delay.calls == [2_000]


def test_retry_after_accepts_an_http_date() -> None:
    assert parse_retry_after_ms("Thu, 01 Jan 2026 00:00:05 GMT", START_MS) == 5_000
    assert parse_retry_after_ms("not-a-date", START_MS) is None
    assert parse_retry_after_ms(None, START_MS) is None


async def test_an_unreasonable_retry_after_fails_fast_instead_of_waiting(
    build_client: Callable[..., DeliveryClient], delay: DelayRecorder
) -> None:
    client = build_client(
        FakeTransport([status(503, {"retry-after": "600"})]), max_retry_after_ms=10_000
    )

    assert await code_of(client.request_quote(QUOTE_REQUEST)) == DELIVERY_UNAVAILABLE
    assert delay.calls == []


async def test_a_malformed_upstream_payload_is_rejected(
    build_client: Callable[..., DeliveryClient],
) -> None:
    client = build_client(FakeTransport([ok({**VALID_QUOTE, "estimated_days": "three"})]))

    assert await code_of(client.request_quote(QUOTE_REQUEST)) == DELIVERY_INVALID_RESPONSE


async def test_a_payload_that_lost_a_required_field_is_rejected(
    build_client: Callable[..., DeliveryClient],
) -> None:
    without_id = {key: value for key, value in VALID_QUOTE.items() if key != "quote_id"}
    client = build_client(FakeTransport([ok(without_id)]))

    assert await code_of(client.request_quote(QUOTE_REQUEST)) == DELIVERY_INVALID_RESPONSE


async def test_the_breaker_opens_and_short_circuits_further_calls(
    build_client: Callable[..., DeliveryClient],
) -> None:
    transport = FakeTransport([status(500)])
    client = build_client(transport, max_attempts=1, failure_threshold=2)

    assert await code_of(client.request_quote(QUOTE_REQUEST)) == DELIVERY_UNAVAILABLE
    assert client.health().circuit_state is CircuitState.CLOSED

    assert await code_of(client.request_quote(QUOTE_REQUEST)) == DELIVERY_UNAVAILABLE
    assert client.health().circuit_state is CircuitState.OPEN

    calls_before = transport.calls
    assert await code_of(client.request_quote(QUOTE_REQUEST)) == DELIVERY_UNAVAILABLE
    # The third call never reached the network.
    assert transport.calls == calls_before


async def test_the_breaker_recovers_when_the_probe_succeeds(
    build_client: Callable[..., DeliveryClient], clock: FakeClock
) -> None:
    transport = FakeTransport([status(500), status(500), ok(VALID_QUOTE)])
    client = build_client(transport, max_attempts=1, failure_threshold=2, cooldown_ms=30_000)

    await code_of(client.request_quote(QUOTE_REQUEST))
    await code_of(client.request_quote(QUOTE_REQUEST))
    assert client.health().circuit_state is CircuitState.OPEN

    clock.advance(29_999)
    assert await code_of(client.request_quote(QUOTE_REQUEST)) == DELIVERY_UNAVAILABLE
    assert transport.calls == 2

    clock.advance(2)
    quote = await client.request_quote(QUOTE_REQUEST)
    assert quote.quote_id == "qte_1"
    assert transport.calls == 3
    assert client.health().circuit_state is CircuitState.CLOSED
    assert client.health().consecutive_failures == 0


async def test_the_breaker_reopens_when_the_probe_fails_again(
    build_client: Callable[..., DeliveryClient], clock: FakeClock
) -> None:
    client = build_client(
        FakeTransport([status(500)]), max_attempts=1, failure_threshold=1, cooldown_ms=10_000
    )

    await code_of(client.request_quote(QUOTE_REQUEST))
    assert client.health().circuit_state is CircuitState.OPEN

    clock.advance(10_000)
    await code_of(client.request_quote(QUOTE_REQUEST))

    health = client.health()
    assert health.circuit_state is CircuitState.OPEN
    assert health.opened_at is not None
    assert health.opened_at.isoformat() == "2026-01-01T00:00:10+00:00"


async def test_a_rejected_request_never_trips_the_breaker(
    build_client: Callable[..., DeliveryClient],
) -> None:
    client = build_client(FakeTransport([status(400)]), max_attempts=1, failure_threshold=2)

    await code_of(client.request_quote(QUOTE_REQUEST))
    await code_of(client.request_quote(QUOTE_REQUEST))

    assert client.health().circuit_state is CircuitState.CLOSED


async def test_health_exposes_the_facts_and_nothing_else(
    build_client: Callable[..., DeliveryClient],
) -> None:
    client = build_client(FakeTransport([status(500)]), max_attempts=1, failure_threshold=1)
    await code_of(client.request_quote(QUOTE_REQUEST))

    assert client.health().model_dump(mode="json", by_alias=True) == {
        "transport": "http",
        "circuitState": "open",
        "consecutiveFailures": 1,
        "lastErrorAt": "2026-01-01T00:00:00.000Z",
        "openedAt": "2026-01-01T00:00:00.000Z",
    }


class _Recorder:
    """Captures the request the HTTP transport actually put on the wire."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.requests: list[Any] = []

    def __call__(self, request: Any) -> Any:
        self.requests.append(request)
        entry = self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]
        if isinstance(entry, Exception):
            raise entry
        return entry


async def test_the_http_transport_sends_what_the_client_asked_for() -> None:
    recorder = _Recorder([httpx.Response(200, json=VALID_QUOTE, headers={"retry-after": "3"})])
    transport = HttpDeliveryTransport(
        base_url="https://carrier.example/",
        api_key="secret-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(recorder)),
    )

    response = await transport.send(
        DeliveryTransportRequest(
            method="POST", path="/v1/quotes", timeout_ms=1_000, body={"order_id": "ord_1"}
        )
    )

    sent = recorder.requests[0]
    assert str(sent.url) == "https://carrier.example/v1/quotes"
    assert sent.headers["authorization"] == "Bearer secret-key"
    assert response.status == 200
    assert response.body == VALID_QUOTE
    # Only the headers the retry logic reads cross the seam.
    assert set(response.headers) <= {"retry-after", "content-type"}


async def test_the_http_transport_translates_a_timeout() -> None:
    recorder = _Recorder([httpx.TimeoutException("too slow")])
    transport = HttpDeliveryTransport(
        base_url="https://carrier.example",
        client=httpx.AsyncClient(transport=httpx.MockTransport(recorder)),
    )

    with pytest.raises(TransportTimeoutError):
        await transport.send(
            DeliveryTransportRequest(method="GET", path="/v1/shipments/x", timeout_ms=1)
        )


async def test_a_non_json_body_is_read_as_no_body() -> None:
    recorder = _Recorder([httpx.Response(500, text="<html>gateway</html>")])
    transport = HttpDeliveryTransport(
        base_url="https://carrier.example",
        client=httpx.AsyncClient(transport=httpx.MockTransport(recorder)),
    )

    response = await transport.send(
        DeliveryTransportRequest(method="GET", path="/v1/shipments/x", timeout_ms=1_000)
    )

    assert response.status == 500
    assert response.body is None
