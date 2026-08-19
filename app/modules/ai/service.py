"""Assistant rules.

Three of them are worth stating before the code. Only the fields listed on the
request schema are ever forwarded to a provider, so a record growing a new
column cannot silently start leaking it. The answer a model gives back is
validated against a closed enum before anything downstream is allowed to act on
it — an unrecognised label is downgraded to ``unknown``, never forwarded. And
identical work is served from the cache, keyed by the *content* of the request
rather than by the record it describes, so two deals with the same facts cost
one call.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, ValidationError

from app.cache.keys import cache_key
from app.modules.ai.prompts import (
    deal_summary_prompt,
    deal_summary_system_prompt,
    inquiry_classification_prompt,
    inquiry_classification_system_prompt,
)
from app.modules.ai.provider import AiCompletionRequest, AiInputTooLargeError, AiProvider
from app.modules.ai.provider_factory import AiConfig
from app.modules.ai.schemas import (
    ClassifyInquiryRequest,
    DealSummaryOut,
    InquiryClassificationOut,
    SummariseDealRequest,
)
from app.modules.ai.types import (
    AI_NAMESPACE,
    DEFAULT_AI_CACHE_TTL_SECONDS,
    DEFAULT_AI_MAX_INPUT_CHARS,
    DEFAULT_AI_MAX_TOKENS,
    CachePort,
    InquiryCategory,
    NoopCache,
    ResolvedInquiryCategory,
    resolve_category,
)

__all__ = ["AiService"]

DEAL_SUMMARY_TASK = "deal-summary"
INQUIRY_CLASSIFICATION_TASK = "inquiry-classification"

#: A classification answer is short by construction; asking for more tokens than
#: a label and a number can occupy only buys the model room to ramble.
CLASSIFICATION_TOKEN_BUDGET = 64

_DIGEST_LENGTH = 32


class _Classification(BaseModel):
    """The shape the classifier is asked to produce.

    The category is validated against the closed list here — the single place
    where a model's free-form answer becomes a value the rest of the system is
    allowed to act on. The confidence is strict about its type so that a model
    answering ``"0.9"`` is treated as a contract violation, not coerced.
    """

    model_config = ConfigDict(extra="ignore")

    category: InquiryCategory
    confidence: StrictFloat | StrictInt = Field(ge=0, le=1)


def _hash_key(task: str, payload: Any) -> str:
    """Builds the cache key from the content of a request.

    The payload is hashed rather than embedded: prompts are long, may contain
    personal data, and a key is not a place either belongs.
    """
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, sort_keys=False)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]
    return cache_key(AI_NAMESPACE, task, digest)


def _extract_json(text: str) -> Any:
    """Pulls the first object-looking span out of an answer.

    Models like to wrap JSON in prose or fences, so the whole answer is not
    trusted to be parseable.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except ValueError:
        return None


def _normalise_inquiry(text: str) -> str:
    """Folds spacing and case so that two spellings of one question share a key."""
    return " ".join(text.split()).lower()


class AiService:
    """Prompt building, provider calls and caching, in that order."""

    def __init__(
        self,
        provider: AiProvider,
        cache: CachePort | None = None,
        config: AiConfig | None = None,
    ) -> None:
        self._provider = provider
        self._cache: CachePort = cache if cache is not None else NoopCache()

        settings = config or AiConfig()
        self._max_tokens = (
            DEFAULT_AI_MAX_TOKENS if settings.max_tokens is None else settings.max_tokens
        )
        self._max_input_chars = (
            DEFAULT_AI_MAX_INPUT_CHARS
            if settings.max_input_chars is None
            else settings.max_input_chars
        )
        self._cache_ttl_seconds = (
            DEFAULT_AI_CACHE_TTL_SECONDS
            if settings.cache_ttl_seconds is None
            else settings.cache_ttl_seconds
        )

    def _assert_within_limit(self, text: str) -> None:
        if len(text) > self._max_input_chars:
            raise AiInputTooLargeError(self._max_input_chars)

    async def summarise_deal(self, request: SummariseDealRequest) -> DealSummaryOut:
        # Only the fields declared on the request schema exist by this point, and
        # the free-text note is the only one that can be long enough to matter.
        self._assert_within_limit(request.notes or "")
        self._assert_within_limit(request.title)

        key = _hash_key(
            DEAL_SUMMARY_TASK,
            {
                "title": request.title,
                "stage": request.stage,
                "amount": request.amount,
                "currency": request.currency,
                "probability": request.probability,
                "expectedCloseDate": request.expected_close_date,
                "notes": request.notes,
            },
        )

        cached = await self._cache.get(key)
        if isinstance(cached, str):
            return DealSummaryOut(
                deal_id=request.id,
                summary=cached,
                provider=self._provider.name,
                cached=True,
            )

        answer = await self._provider.complete(
            AiCompletionRequest(
                system=deal_summary_system_prompt(),
                prompt=deal_summary_prompt(request),
                max_tokens=self._max_tokens,
            )
        )
        summary = answer.strip()

        await self._cache.set(key, summary, self._cache_ttl_seconds)
        return DealSummaryOut(
            deal_id=request.id,
            summary=summary,
            provider=self._provider.name,
            cached=False,
        )

    async def classify_inquiry(self, request: ClassifyInquiryRequest) -> InquiryClassificationOut:
        self._assert_within_limit(request.text)

        key = _hash_key(INQUIRY_CLASSIFICATION_TASK, _normalise_inquiry(request.text))

        cached = self._read_cached_classification(await self._cache.get(key))
        if cached is not None:
            category, confidence = cached
            return InquiryClassificationOut(
                category=category,
                confidence=confidence,
                provider=self._provider.name,
                cached=True,
            )

        answer = await self._provider.complete(
            AiCompletionRequest(
                system=inquiry_classification_system_prompt(),
                prompt=inquiry_classification_prompt(request.text),
                max_tokens=min(self._max_tokens, CLASSIFICATION_TOKEN_BUDGET),
            )
        )

        # An unrecognised label is downgraded, never forwarded: the caller gets a
        # value it can switch on, and a hallucinated category cannot become a
        # routing decision or a database row.
        try:
            parsed = _Classification.model_validate(_extract_json(answer))
        except ValidationError:
            category = ResolvedInquiryCategory.UNKNOWN
            confidence = 0.0
        else:
            category = resolve_category(parsed.category)
            confidence = float(parsed.confidence)

        await self._cache.set(
            key,
            {"category": category.value, "confidence": confidence},
            self._cache_ttl_seconds,
        )
        return InquiryClassificationOut(
            category=category,
            confidence=confidence,
            provider=self._provider.name,
            cached=False,
        )

    @staticmethod
    def _read_cached_classification(
        payload: Any,
    ) -> tuple[ResolvedInquiryCategory, float] | None:
        """Rebuilds a cached verdict, or reports a miss for anything unrecognised.

        A cache may hold an entry written by an older version of this code, and
        treating that as "not cached" is always safe, whereas trusting it is not.
        """
        if not isinstance(payload, dict):
            return None
        raw_category = payload.get("category")
        raw_confidence = payload.get("confidence")
        if not isinstance(raw_category, str) or not isinstance(raw_confidence, int | float):
            return None
        if raw_category not in tuple(ResolvedInquiryCategory):
            return None
        return ResolvedInquiryCategory(raw_category), float(raw_confidence)
