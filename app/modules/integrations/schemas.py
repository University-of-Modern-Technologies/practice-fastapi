"""Request payloads of the integrations module.

Nothing here is strict about unknown keys: a client that sends one extra field
gets its request served, exactly as the rest of this API behaves. What *is*
strict is every value we forward to a third party — a malformed postal code or a
five-tonne "parcel" must fail here, on our side of the boundary, rather than as
an opaque rejection from the carrier three seconds later.

The validated models are also the shapes the service and the client consume:
the framework parses straight into them, so there is no second hand-written
translation step that could drift from the schema.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from app.core.responses import CamelModel

__all__ = [
    "CreateShipmentData",
    "CreateShipmentRequest",
    "DeliveryAddress",
    "DeliveryParcel",
    "QuoteRequest",
    "QuoteRequestData",
    "ShipmentId",
]

#: ISO 3166-1 alpha-2. Upper-cased on the way in so that ``pl`` and ``PL`` do
#: not become two different cache entries for the same route.
CountryCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{2}$"),
]
City = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
PostalCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
AddressLine = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OrderId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
QuoteId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
ShipmentId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]

#: A monetary amount travels as a string, as it does everywhere else in this API.
MoneyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^\d{1,12}(?:\.\d{1,2})?$"),
]


class DeliveryAddress(CamelModel):
    """Where a parcel is picked up from, or delivered to."""

    country: CountryCode
    city: City
    postal_code: PostalCode
    line1: AddressLine


class DeliveryParcel(CamelModel):
    """Physical dimensions the carrier prices against.

    The upper bounds are what a parcel service accepts at all; anything larger
    is freight, which this integration does not book.
    """

    weight_grams: int = Field(ge=1, le=1_000_000)
    length_cm: int = Field(ge=1, le=500)
    width_cm: int = Field(ge=1, le=500)
    height_cm: int = Field(ge=1, le=500)


class QuoteRequest(CamelModel):
    """Everything the carrier needs in order to price one parcel."""

    order_id: OrderId
    origin: DeliveryAddress
    destination: DeliveryAddress
    parcel: DeliveryParcel
    declared_value: MoneyString | None = None


class CreateShipmentRequest(CamelModel):
    """Books a previously quoted parcel with the carrier."""

    quote_id: QuoteId
    order_id: OrderId
    destination: DeliveryAddress
    parcel: DeliveryParcel
    reference: Reference | None = None


#: Names used by the client and the service, which think in domain terms rather
#: than in HTTP ones.
QuoteRequestData = QuoteRequest
CreateShipmentData = CreateShipmentRequest
