"""Wire contract of the assistant endpoints.

The request bodies are the allow-list. Nothing is spread from a database record
and unknown fields are dropped on the way in, so a column added later — a token,
a hash, a note carrying personal data — cannot silently start leaving the system
inside a prompt.

Input is bounded here as well as in the service: oversized text is rejected with
a 400 before a single token is paid for.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import Field, StringConstraints

from app.core.responses import CamelModel
from app.modules.ai.types import DEFAULT_AI_MAX_INPUT_CHARS, ResolvedInquiryCategory

MAX_TITLE_LENGTH = 200
MAX_STAGE_LENGTH = 40
MIN_PROBABILITY = 0
MAX_PROBABILITY = 100

#: Up to twelve integer digits and at most two decimals — the range the
#: ``Numeric(14, 2)`` columns of this system hold exactly. A leading sign is not
#: part of the grammar, so a negative amount never reaches a prompt.
MONEY_PATTERN = r"^\d{1,12}(?:\.\d{1,2})?$"

DealTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITLE_LENGTH)
]

DealStageName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_STAGE_LENGTH)
]

MoneyAmount = Annotated[str, StringConstraints(strip_whitespace=True, pattern=MONEY_PATTERN)]

CurrencyCode = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{3}$")
]

#: A plain calendar day, kept as text: it is a label in a prompt, never a value
#: this module does arithmetic on.
CalendarDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]

FreeText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=DEFAULT_AI_MAX_INPUT_CHARS),
]


class SummariseDealRequest(CamelModel):
    """Body of ``POST /ai/summaries/deal``.

    The exact, explicitly listed fields of a deal that may be sent to a
    provider — an allow-list is the only reliable way to keep that promise.
    """

    id: uuid.UUID
    title: DealTitle
    stage: DealStageName
    amount: MoneyAmount | None = None
    currency: CurrencyCode | None = None
    probability: int | None = Field(default=None, ge=MIN_PROBABILITY, le=MAX_PROBABILITY)
    expected_close_date: CalendarDate | None = None
    notes: FreeText | None = None


class ClassifyInquiryRequest(CamelModel):
    """Body of ``POST /ai/classify/inquiry``."""

    text: FreeText


class DealSummaryOut(CamelModel):
    """A summary, plus enough provenance for the client to trust it or not."""

    deal_id: uuid.UUID
    summary: str
    provider: str
    cached: bool


class InquiryClassificationOut(CamelModel):
    """A label from the closed list, or ``unknown``, never anything else."""

    category: ResolvedInquiryCategory
    confidence: float = Field(ge=0, le=1)
    provider: str
    cached: bool
