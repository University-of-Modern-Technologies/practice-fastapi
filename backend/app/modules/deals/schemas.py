"""Wire contract of the deals endpoints.

Two things are pinned here rather than left to a default. An amount travels as
a fixed-scale string, because the client's only number type cannot hold it
exactly. And ``stage`` appears in no update body at all: the pipeline is the
server's to advance, so the field is simply absent from the shape a ``PATCH``
accepts, and ``extra="forbid"`` turns an attempt to smuggle it in into a
rejected request rather than a silent no-op.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BeforeValidator,
    Field,
    PlainSerializer,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE, MAX_PAGE_SIZE, SortOrder
from app.core.responses import CamelModel
from app.core.serializers import Money, UtcDatetime
from app.core.validation import IsoDate
from app.db.enums import DealStage
from app.modules.deals.transition import MAX_PROBABILITY, MIN_PROBABILITY
from app.modules.deals.types import (
    MAX_SEARCH_LENGTH,
    MAX_TITLE_LENGTH,
    DealSortField,
)

#: Up to twelve digits and at most two decimals — the shape ``Numeric(14, 2)``
#: can hold without rounding.
AMOUNT_PATTERN = re.compile(r"^\d{1,12}(?:\.\d{1,2})?$")
CURRENCY_PATTERN = re.compile(r"^[A-Za-z]{3}$")
CURRENCY_LENGTH = 3


def _parse_amount(value: object) -> object:
    """Reads an amount from the wire without ever going through a float.

    Only a string is accepted: a JSON number has already lost precision by the
    time it reaches this validator, and accepting it would make the loss
    invisible.
    """
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str) or not AMOUNT_PATTERN.fullmatch(value.strip()):
        message = "Amount must be a decimal string with up to two fractional digits"
        raise ValueError(message)
    return Decimal(value.strip())


def _parse_currency(value: object) -> object:
    if not isinstance(value, str):
        return value
    code = value.strip()
    if not CURRENCY_PATTERN.fullmatch(code):
        message = "Currency must be a three-letter code"
        raise ValueError(message)
    return code.upper()


def _format_calendar_date(value: date) -> str:
    return value.isoformat()


def _require_json_number(value: object) -> object:
    """Refuses a number that arrived as text or as a boolean.

    A request body is JSON, which has a number type of its own; ``"3"`` or
    ``true`` where a count belongs is a malformed request, not a value to
    convert. ``None`` is left to the field's own optionality.
    """
    if isinstance(value, bool | str):
        message = "Input should be a valid integer"
        raise ValueError(message)
    return value


def _trim(value: object) -> object:
    """Strips surrounding whitespace, leaving anything that is not text alone."""
    return value.strip() if isinstance(value, str) else value


def _reject_null(value: object) -> object:
    """Refuses an explicitly sent ``null``.

    A default is never passed through a validator, so this only ever sees a
    value the client wrote down: a field may be omitted freely, while ``null``
    stays an error on the fields whose column cannot hold one.
    """
    if value is None:
        message = "Value may not be null"
        raise ValueError(message)
    return value


#: Published as what the validator accepts, a decimal string; the schema the
#: framework derives for a ``Decimal`` would also offer a JSON number.
AmountIn = Annotated[
    Decimal,
    BeforeValidator(_parse_amount),
    WithJsonSchema({"type": "string", "pattern": AMOUNT_PATTERN.pattern}),
]
CurrencyIn = Annotated[str, BeforeValidator(_parse_currency)]
Probability = Annotated[int, Field(ge=MIN_PROBABILITY, le=MAX_PROBABILITY)]
#: The same bound as it arrives in a request body, where it must be a number.
BodyProbability = Annotated[Probability, BeforeValidator(_require_json_number)]
#: A calendar day on the way in: ``YYYY-MM-DD`` text only, never a timestamp.
CalendarDateIn = IsoDate
#: A calendar day on the way out, in the same ``YYYY-MM-DD`` form it came in.
#: It is the same day for everybody who reads it, so it is not an instant.
CalendarDateOut = Annotated[
    date,
    PlainSerializer(_format_calendar_date, return_type=str),
    WithJsonSchema({"type": "string", "format": "date"}, mode="serialization"),
]
#: Optimistic locking counter as the client echoes it back.
Version = Annotated[int, Field(ge=1), BeforeValidator(_require_json_number)]
#: Trimmed before it is measured, so a title of spaces is an empty title.
Title = Annotated[str, Field(min_length=1, max_length=MAX_TITLE_LENGTH), BeforeValidator(_trim)]


class DealOut(CamelModel):
    """A deal as the API publishes it."""

    id: uuid.UUID
    owner_id: uuid.UUID
    contact_id: uuid.UUID | None
    title: str
    stage: DealStage
    amount: Money
    currency: str
    probability: int
    version: int
    expected_close_date: CalendarDateOut | None
    closed_at: UtcDatetime | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class CreateDealRequest(CamelModel):
    """Body of ``POST /deals``.

    ``stage`` is accepted only as the literal ``LEAD``: a deal has to start at
    the beginning of the pipeline, and allowing anything else on creation would
    be a way around the machine.
    """

    owner_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    title: Title
    stage: Literal[DealStage.LEAD] | None = None
    amount: AmountIn
    currency: CurrencyIn | None = None
    probability: BodyProbability | None = None
    expected_close_date: CalendarDateIn | None = None

    # Every optional field here may be left out, but none may be sent as null:
    # a new deal has nothing to clear.
    @field_validator(
        "owner_id",
        "contact_id",
        "stage",
        "currency",
        "probability",
        "expected_close_date",
        mode="before",
    )
    @classmethod
    def _require_value(cls, value: object) -> object:
        return _reject_null(value)


class UpdateDealRequest(CamelModel):
    """Body of ``PATCH /deals/{id}``.

    Every field but ``version`` is optional, and an absent field means "leave
    as is" — which is why the service reads ``model_fields_set`` rather than the
    values. ``contactId`` and ``expectedCloseDate`` are the two that also accept
    an explicit ``null``, meaning "clear it".
    """

    version: Version
    owner_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    title: Title | None = None
    amount: AmountIn | None = None
    currency: CurrencyIn | None = None
    probability: BodyProbability | None = None
    expected_close_date: CalendarDateIn | None = None

    # These back non-nullable columns, so an explicit null is a bad request
    # rather than a silent no-op that still moves the version on.
    @field_validator("owner_id", "title", "amount", "currency", "probability", mode="before")
    @classmethod
    def _require_value(cls, value: object) -> object:
        return _reject_null(value)

    @model_validator(mode="after")
    def _require_one_field(self) -> Self:
        if self.model_fields_set <= {"version"}:
            message = "At least one field to update is required"
            raise ValueError(message)
        return self


class TransitionDealRequest(CamelModel):
    """Body of ``POST /deals/{id}/transitions``."""

    version: Version
    stage: DealStage
    probability: BodyProbability | None = None

    @field_validator("probability", mode="before")
    @classmethod
    def _require_value(cls, value: object) -> object:
        return _reject_null(value)


class DealListParams(CamelModel):
    """Filters accepted when browsing deals.

    Grouped into a model rather than spelled out as a dozen handler arguments;
    FastAPI reads a model as query parameters just as happily, and the two
    range checks below have somewhere to live.

    Unlike a request body, an unknown parameter here is ignored rather than
    refused: a query string picks up cache-busters and tracking keys on the way
    through a browser, and none of them are the client asking for anything.
    """

    page: int = Field(default=1, ge=1, le=MAX_PAGE)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    search: str | None = Field(default=None, min_length=1, max_length=MAX_SEARCH_LENGTH)
    owner_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    stage: DealStage | None = None
    min_amount: AmountIn | None = None
    max_amount: AmountIn | None = None
    min_probability: Probability | None = None
    max_probability: Probability | None = None
    expected_close_from: CalendarDateIn | None = None
    expected_close_to: CalendarDateIn | None = None
    sort_by: DealSortField = "createdAt"
    sort_order: SortOrder = "desc"

    # Trimmed before the length is checked, so a search of spaces is refused
    # as empty rather than turned into "no filter".
    @field_validator("search", mode="before")
    @classmethod
    def _trim_search(cls, value: object) -> object:
        return _trim(value)

    @model_validator(mode="after")
    def _require_ordered_ranges(self) -> Self:
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            message = "minAmount must not exceed maxAmount"
            raise ValueError(message)
        if (
            self.min_probability is not None
            and self.max_probability is not None
            and self.min_probability > self.max_probability
        ):
            message = "minProbability must not exceed maxProbability"
            raise ValueError(message)
        return self
