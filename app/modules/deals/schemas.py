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

from pydantic import BeforeValidator, Field, field_validator, model_validator

from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, SortOrder
from app.core.responses import CamelModel
from app.core.serializers import Money, UtcDate, UtcDatetime
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


AmountIn = Annotated[Decimal, BeforeValidator(_parse_amount)]
CurrencyIn = Annotated[str, BeforeValidator(_parse_currency)]
Probability = Annotated[int, Field(ge=MIN_PROBABILITY, le=MAX_PROBABILITY)]
#: Optimistic locking counter as the client echoes it back.
Version = Annotated[int, Field(ge=1)]
Title = Annotated[str, Field(min_length=1, max_length=MAX_TITLE_LENGTH)]


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
    expected_close_date: UtcDate | None
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
    probability: Probability | None = None
    expected_close_date: date | None = None


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
    probability: Probability | None = None
    expected_close_date: date | None = None

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
    probability: Probability | None = None


class DealListParams(CamelModel):
    """Filters accepted when browsing deals.

    Grouped into a model rather than spelled out as a dozen handler arguments;
    FastAPI reads a model as query parameters just as happily, and the two
    range checks below have somewhere to live.

    Unlike a request body, an unknown parameter here is ignored rather than
    refused: a query string picks up cache-busters and tracking keys on the way
    through a browser, and none of them are the client asking for anything.
    """

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    search: str | None = Field(default=None, min_length=1, max_length=MAX_SEARCH_LENGTH)
    owner_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    stage: DealStage | None = None
    min_amount: AmountIn | None = None
    max_amount: AmountIn | None = None
    min_probability: Probability | None = None
    max_probability: Probability | None = None
    expected_close_from: date | None = None
    expected_close_to: date | None = None
    sort_by: DealSortField = "createdAt"
    sort_order: SortOrder = "desc"

    @field_validator("search")
    @classmethod
    def _trim_search(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

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
