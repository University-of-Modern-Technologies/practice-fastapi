"""The default provider: deterministic, offline, no API key, no cost.

It exists so the feature is complete on a fresh checkout — routes answer, tests
run, the UI has something to render — without anybody signing up for a model
vendor. It is a *stand-in*, not a model: it templates an answer from the prompt
it is given, and it is intentionally obvious about it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from app.modules.ai.prompts import (
    CLASSIFY_INQUIRY_TASK,
    SUMMARIZE_DEAL_TASK,
    UNTRUSTED_CLOSE,
    UNTRUSTED_OPEN,
)
from app.modules.ai.provider import AiCompletionRequest, AiProvider
from app.modules.ai.types import INQUIRY_CATEGORIES, InquiryCategory

__all__ = [
    "MOCK_AI_PROVIDER_NAME",
    "MockAiProvider",
    "create_mock_ai_provider",
    "mock_known_categories",
]

MOCK_AI_PROVIDER_NAME = "mock"

#: Order matters: the first category whose keyword appears wins, so the more
#: specific buckets are listed before the general ones.
_KEYWORDS: tuple[tuple[InquiryCategory, tuple[str, ...]], ...] = (
    (InquiryCategory.BILLING, ("invoice", "payment", "refund", "charge", "billing", "price")),
    (
        InquiryCategory.SHIPPING,
        ("delivery", "shipment", "parcel", "tracking", "courier", "shipping"),
    ),
    (
        InquiryCategory.TECHNICAL_SUPPORT,
        ("error", "bug", "crash", "login", "broken", "not working"),
    ),
    (
        InquiryCategory.COMPLAINT,
        ("complaint", "unacceptable", "angry", "terrible", "disappointed"),
    ),
    (InquiryCategory.SALES, ("quote", "demo", "pricing plan", "buy", "purchase", "upgrade")),
)

_KEYWORD_CONFIDENCE = 0.72
_FALLBACK_CONFIDENCE = 0.4

#: A crude but honest stand-in for the token budget: four characters per token is
#: the usual rule of thumb, so callers still see truncation.
_CHARS_PER_TOKEN = 4

_TITLE_LABEL = "Title: "
_FIELD_SEPARATOR = ": "


def _untrusted_block(prompt: str) -> str:
    """Returns only what the caller supplied, without the surrounding prompt."""
    start = prompt.find(UNTRUSTED_OPEN)
    end = prompt.find(UNTRUSTED_CLOSE)
    if start == -1 or end == -1 or end < start:
        return ""
    return prompt[start + len(UNTRUSTED_OPEN) : end].strip()


def _classify(prompt: str) -> str:
    # Only the untrusted block is inspected, and only for keywords. Even the mock
    # treats that text as data it reads, never as instructions it obeys.
    haystack = _untrusted_block(prompt).lower()

    for category, keywords in _KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return json.dumps(
                {"category": category.value, "confidence": _KEYWORD_CONFIDENCE},
                separators=(",", ":"),
            )

    return json.dumps(
        {"category": InquiryCategory.OTHER.value, "confidence": _FALLBACK_CONFIDENCE},
        separators=(",", ":"),
    )


def _summarise(prompt: str) -> str:
    facts = [
        line
        for line in (raw.strip() for raw in prompt.split("\n"))
        if line and _FIELD_SEPARATOR in line and not line.startswith(UNTRUSTED_OPEN)
    ]

    title = next(
        (line[len(_TITLE_LABEL) :] for line in facts if line.startswith(_TITLE_LABEL)), "Deal"
    )
    details = "; ".join(line for line in facts if not line.startswith(_TITLE_LABEL))

    if not details:
        return f"{title}: no further details were provided."
    return f"{title}. Current state — {details}. Generated offline without a language model."


class MockAiProvider:
    """Templated answers, produced without a network call of any kind."""

    name = MOCK_AI_PROVIDER_NAME

    async def complete(self, request: AiCompletionRequest) -> str:
        if CLASSIFY_INQUIRY_TASK in request.system:
            text = _classify(request.prompt)
        elif SUMMARIZE_DEAL_TASK in request.system:
            text = _summarise(request.prompt)
        else:
            text = "No offline template is available for this task."

        return text[: max(1, request.max_tokens * _CHARS_PER_TOKEN)]


def create_mock_ai_provider() -> AiProvider:
    """Builds the offline provider."""
    return MockAiProvider()


#: Exposed so tests can assert the closed list has not silently drifted.
mock_known_categories: Sequence[InquiryCategory] = INQUIRY_CATEGORIES
