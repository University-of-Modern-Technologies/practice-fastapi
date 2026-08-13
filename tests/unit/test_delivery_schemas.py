"""Translation of the carrier's wire shape into the domain DTO."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.integrations.delivery.schemas import (
    UpstreamQuote,
    UpstreamShipment,
    to_delivery_quote_dto,
    to_shipment_dto,
)

QUOTE = {
    "quote_id": "qte_1",
    "carrier": "Test Carrier",
    "service": "standard",
    "amount": "12.50",
    "currency": "eur",
    "estimated_days": 3,
    "expires_at": "2026-01-01T00:00:00.000Z",
}

SHIPMENT = {
    "shipment_id": "shp_1",
    "order_id": "ord_1",
    "status": "CREATED",
    "carrier": "Test Carrier",
    "tracking_number": "TRK1",
    "created_at": "2026-01-01T00:00:00.000Z",
    "estimated_delivery_at": "2026-01-04T00:00:00.000Z",
}

# Spellings a provider may legitimately use that are *not* the one this service
# would have produced on its own. Each has to survive untouched.
FOREIGN_SPELLINGS = [
    "2026-03-01T12:30:00Z",
    "2026-03-01T12:30:00+02:00",
    "2026-03-01T12:30:00.123456Z",
    "2026-03-01T12:30:00.5-05:00",
]


@pytest.mark.parametrize("written", FOREIGN_SPELLINGS)
def test_a_quote_expiry_is_forwarded_exactly_as_written(written: str) -> None:
    """The instant is the provider's statement, not ours to re-render."""
    dto = to_delivery_quote_dto(UpstreamQuote.model_validate({**QUOTE, "expires_at": written}))

    assert dto.expires_at == written


@pytest.mark.parametrize("written", FOREIGN_SPELLINGS)
def test_shipment_timestamps_are_forwarded_exactly_as_written(written: str) -> None:
    shipment = UpstreamShipment.model_validate(
        {**SHIPMENT, "created_at": written, "estimated_delivery_at": written}
    )
    dto = to_shipment_dto(shipment)

    assert dto.created_at == written
    assert dto.estimated_delivery_at == written


def test_the_serialized_payload_keeps_the_provider_spelling() -> None:
    """Nothing between validation and the wire rewrites it either."""
    written = "2026-03-01T12:30:00+02:00"
    dto = to_delivery_quote_dto(UpstreamQuote.model_validate({**QUOTE, "expires_at": written}))

    assert dto.model_dump(mode="json", by_alias=True)["expiresAt"] == written


def test_an_absent_estimated_delivery_stays_absent() -> None:
    shipment = UpstreamShipment.model_validate({**SHIPMENT, "estimated_delivery_at": None})

    assert to_shipment_dto(shipment).estimated_delivery_at is None


@pytest.mark.parametrize(
    "written",
    [
        "not-a-timestamp",
        # An instant without a zone is not an instant; reading it as UTC would
        # invent a fact the provider never stated.
        "2026-03-01T12:30:00",
        "",
    ],
)
def test_a_timestamp_that_is_not_an_instant_is_rejected(written: str) -> None:
    with pytest.raises(ValidationError):
        UpstreamQuote.model_validate({**QUOTE, "expires_at": written})
