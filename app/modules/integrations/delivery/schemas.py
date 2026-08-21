"""Contracts for the *upstream* payloads.

Nothing that comes back from a service we do not control is trusted: every
response is parsed through one of these models before a single field of it is
read. If the provider renames a field or starts returning ``null`` where a
number used to be, the failure surfaces here as a controlled
``DELIVERY_INVALID_RESPONSE`` instead of as an ``AttributeError`` thrown three
layers deeper.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.modules.integrations.types import (
    DeliveryQuoteDto,
    ShipmentDto,
    ShipmentStatus,
)

__all__ = [
    "UpstreamQuote",
    "UpstreamShipment",
    "to_delivery_quote_dto",
    "to_shipment_dto",
]

MoneyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^\d{1,12}(?:\.\d{1,2})?$"),
]
CurrencyCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{3}$"),
]
NonEmpty = Annotated[str, StringConstraints(min_length=1)]


def _ensure_instant(value: str) -> str:
    """Proves the timestamp is an instant without rewriting it.

    Parsing is a check, not a conversion: the string that comes back is the one
    the provider sent. Re-rendering it in our own notation would restate a third
    party's fact, exactly as re-scaling their price would.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        message = "Invalid ISO-8601 timestamp"
        raise ValueError(message) from error
    if parsed.tzinfo is None:
        message = "Timestamp must carry a UTC offset"
        raise ValueError(message)
    return value


#: An ISO-8601 instant kept in the provider's own spelling.
IsoInstant = Annotated[str, AfterValidator(_ensure_instant)]

MAX_ESTIMATED_DAYS = 365


class UpstreamPayload(BaseModel):
    """Base for the wire shapes.

    The field names are the provider's, in snake_case, and are read literally:
    guessing at an alias for somebody else's contract is how a silent mismatch
    starts. A timestamp must carry a zone — an instant without one is not an
    instant, and treating it as UTC would invent a fact.
    """

    model_config = ConfigDict(populate_by_name=False)


class UpstreamQuote(UpstreamPayload):
    quote_id: NonEmpty
    carrier: NonEmpty
    service: NonEmpty
    amount: MoneyString
    currency: CurrencyCode
    estimated_days: int = Field(ge=0, le=MAX_ESTIMATED_DAYS)
    expires_at: IsoInstant


class UpstreamShipment(UpstreamPayload):
    shipment_id: NonEmpty
    order_id: NonEmpty
    status: ShipmentStatus
    carrier: NonEmpty
    tracking_number: NonEmpty | None = None
    created_at: IsoInstant
    estimated_delivery_at: IsoInstant | None = None


# The snake-case wire shape is translated into the camel-case domain DTO in
# exactly one place, so renaming a field upstream is a one-line change here.
def to_delivery_quote_dto(quote: UpstreamQuote) -> DeliveryQuoteDto:
    return DeliveryQuoteDto(
        quote_id=quote.quote_id,
        carrier=quote.carrier,
        service=quote.service,
        # The amount and the expiry are forwarded exactly as the provider wrote
        # them. Restating a third party's figures in our own notation is how a
        # value the carrier never quoted reaches the client.
        amount=quote.amount,
        currency=quote.currency,
        estimated_days=quote.estimated_days,
        expires_at=quote.expires_at,
    )


def to_shipment_dto(shipment: UpstreamShipment) -> ShipmentDto:
    return ShipmentDto(
        shipment_id=shipment.shipment_id,
        order_id=shipment.order_id,
        status=shipment.status,
        carrier=shipment.carrier,
        tracking_number=shipment.tracking_number,
        created_at=shipment.created_at,
        estimated_delivery_at=shipment.estimated_delivery_at,
    )
