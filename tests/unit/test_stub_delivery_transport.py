"""The stub carrier: the ids it hands out have to be reproducible."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from app.modules.integrations.delivery.stub_transport import StubDeliveryTransport
from app.modules.integrations.delivery.transport import DeliveryTransportRequest

NOW_MS = 1_767_225_600_000.0

QUOTE_BODY: dict[str, Any] = {
    "order_id": "ord_1",
    "origin": {"country": "PL", "city": "Warsaw", "postalCode": "00-001", "line1": "Street 1"},
    "destination": {"country": "DE", "city": "Berlin", "postalCode": "10115", "line1": "Straße 2"},
    "parcel": {"weightGrams": 1_000, "lengthCm": 10, "widthCm": 10, "heightCm": 10},
}


def _transport() -> StubDeliveryTransport:
    return StubDeliveryTransport(now_ms=lambda: NOW_MS)


async def _quote(body: dict[str, Any]) -> dict[str, Any]:
    response = await _transport().send(
        DeliveryTransportRequest(method="POST", path="/v1/quotes", body=body, timeout_ms=1_000)
    )
    assert isinstance(response.body, dict)
    return response.body


async def test_the_quote_id_is_the_documented_digest_of_the_payload() -> None:
    """The id is pinned to one serialisation: insertion order, unescaped text.

    Any other spelling of the same payload would silently produce a different
    id, and the stub would stop being usable as a fixture.
    """
    encoded = json.dumps(QUOTE_BODY, separators=(",", ":"), ensure_ascii=False)
    expected = f"qte_{sha256(encoded.encode()).hexdigest()[:16]}"

    assert (await _quote(QUOTE_BODY))["quote_id"] == expected


async def test_the_same_request_always_prices_to_the_same_id() -> None:
    assert (await _quote(QUOTE_BODY))["quote_id"] == (await _quote(QUOTE_BODY))["quote_id"]


async def test_a_different_request_prices_to_a_different_id() -> None:
    other = {**QUOTE_BODY, "order_id": "ord_2"}

    assert (await _quote(QUOTE_BODY))["quote_id"] != (await _quote(other))["quote_id"]


async def test_a_shipment_id_and_its_tracking_number_are_reproducible() -> None:
    transport = _transport()
    body = {"quote_id": "qte_1", "order_id": "ord_1", "parcel": QUOTE_BODY["parcel"]}

    first = await transport.send(
        DeliveryTransportRequest(method="POST", path="/v1/shipments", body=body, timeout_ms=1_000)
    )
    second = await _transport().send(
        DeliveryTransportRequest(method="POST", path="/v1/shipments", body=body, timeout_ms=1_000)
    )

    assert isinstance(first.body, dict)
    assert isinstance(second.body, dict)
    assert first.body["shipment_id"] == second.body["shipment_id"]
    assert first.body["tracking_number"] == second.body["tracking_number"]
