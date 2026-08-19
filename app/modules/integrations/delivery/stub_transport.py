"""In-repo stand-in for the delivery provider.

The default configuration has no base URL, and without this the whole feature
would be dead on a fresh checkout. The stub keeps the system runnable end to end
with no account, no key and no network: it speaks exactly the wire format the
real service is documented to speak, so the client code under test is the same
code that runs in production.

It is deterministic — the same order always produces the same quote — which
makes it usable as a fixture as well as a placeholder.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import unquote

from app.core.serializers import format_datetime, format_scaled_money
from app.modules.integrations.delivery.circuit_breaker import default_now_ms
from app.modules.integrations.delivery.transport import (
    DeliveryTransportRequest,
    DeliveryTransportResponse,
)
from app.modules.integrations.types import ShipmentStatus, TransportKind

__all__ = ["StubDeliveryTransport"]

CARRIER = "Stub Express"
DAY_MS = 24 * 60 * 60 * 1_000
QUOTES_PATH = "/v1/quotes"
SHIPMENTS_PATH = "/v1/shipments"
SHIPMENT_PATH_PREFIX = f"{SHIPMENTS_PATH}/"

#: Above this weight the parcel network refuses the parcel and quotes freight.
FREIGHT_WEIGHT_GRAMS = 20_000
DEFAULT_WEIGHT_GRAMS = 1_000
#: Flat fee plus a linear weight component, in whole cents.
BASE_FEE_CENTS = 499
CENTS_PER_100_GRAMS = 25


def _digest(prefix: str, value: Any) -> str:
    """A short, stable id derived from the payload.

    The payload is serialised exactly as it was built — insertion order, no
    escaping of non-ASCII characters — because the same request must yield the
    same id in every deployment of this stub, and any other serialisation would
    silently produce a different one.
    """
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)
    return f"{prefix}_{hashlib.sha256(encoded.encode()).hexdigest()[:16]}"


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_number(value: Any, fallback: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


def _json(status: int, body: Any) -> DeliveryTransportResponse:
    return DeliveryTransportResponse(
        status=status, headers={"content-type": "application/json"}, body=body
    )


def _instant(now_ms: float) -> datetime:
    return datetime.fromtimestamp(now_ms / 1000.0, UTC)


class StubDeliveryTransport:
    """Answers the documented delivery protocol from memory."""

    kind: TransportKind = TransportKind.STUB

    def __init__(self, *, now_ms: Callable[[], float] = default_now_ms) -> None:
        self._now_ms = now_ms
        self._shipments: dict[str, dict[str, Any]] = {}

    def _quote_for(self, body: Any) -> DeliveryTransportResponse:
        payload = _as_mapping(body)
        parcel = _as_mapping(payload.get("parcel"))
        weight_grams = _read_number(parcel.get("weightGrams"), DEFAULT_WEIGHT_GRAMS)
        cents = BASE_FEE_CENTS + math.ceil(weight_grams / 100) * CENTS_PER_100_GRAMS
        heavy = weight_grams > FREIGHT_WEIGHT_GRAMS

        return _json(
            200,
            {
                "quote_id": _digest("qte", payload),
                "carrier": CARRIER,
                "service": "freight" if heavy else "standard",
                "amount": format_scaled_money(Decimal(cents) / 100),
                "currency": "EUR",
                "estimated_days": 5 if heavy else 3,
                "expires_at": format_datetime(_instant(self._now_ms() + DAY_MS)),
            },
        )

    def _create_shipment(self, body: Any) -> DeliveryTransportResponse:
        payload = _as_mapping(body)
        raw_order_id = payload.get("order_id")
        order_id = raw_order_id if isinstance(raw_order_id, str) else "unknown-order"
        shipment_id = _digest("shp", payload)
        now_ms = self._now_ms()
        shipment: dict[str, Any] = {
            "shipment_id": shipment_id,
            "order_id": order_id,
            "status": ShipmentStatus.CREATED.value,
            "carrier": CARRIER,
            "tracking_number": _digest("trk", shipment_id).upper(),
            "created_at": format_datetime(_instant(now_ms)),
            "estimated_delivery_at": format_datetime(_instant(now_ms + 3 * DAY_MS)),
        }
        self._shipments[shipment_id] = shipment
        return _json(201, shipment)

    async def send(self, request: DeliveryTransportRequest) -> DeliveryTransportResponse:
        if request.method == "POST" and request.path == QUOTES_PATH:
            return self._quote_for(request.body)

        if request.method == "POST" and request.path == SHIPMENTS_PATH:
            return self._create_shipment(request.body)

        if request.method == "GET" and request.path.startswith(SHIPMENT_PATH_PREFIX):
            shipment_id = unquote(request.path[len(SHIPMENT_PATH_PREFIX) :])
            shipment = self._shipments.get(shipment_id)
            if shipment is None:
                return _json(404, {"error": "not_found"})
            return _json(200, {**shipment, "status": ShipmentStatus.IN_TRANSIT.value})

        return _json(404, {"error": "not_found"})
