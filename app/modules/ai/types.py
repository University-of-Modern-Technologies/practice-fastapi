"""Vocabulary of the assistant module.

Two things are worth stating before the code. The list of categories the
classifier may return is *closed*: a language model will happily invent a label,
and an invented label that reaches a routing rule or a database row is a bug
waiting to happen. And the cache is described as a protocol rather than
imported, so the assistant compiles, runs and is testable without a cache
backend being wired in at all.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from typing import Any, Final, Protocol

__all__ = [
    "AI_NAMESPACE",
    "DEFAULT_AI_CACHE_TTL_SECONDS",
    "DEFAULT_AI_MAX_INPUT_CHARS",
    "DEFAULT_AI_MAX_TOKENS",
    "INQUIRY_CATEGORIES",
    "UNKNOWN_INQUIRY_CATEGORY",
    "CachePort",
    "InquiryCategory",
    "LoggerPort",
    "NoopCache",
    "ResolvedInquiryCategory",
    "resolve_category",
]

#: Cache namespace of everything this module stores, so the whole set can be
#: dropped with a single prefix scan.
AI_NAMESPACE = "ai"

#: Hard cap on the answer requested from a provider, so one call cannot run away
#: with cost.
DEFAULT_AI_MAX_TOKENS = 400
#: Hard cap on user-supplied input, enforced before any prompt is built.
DEFAULT_AI_MAX_INPUT_CHARS = 4_000
DEFAULT_AI_CACHE_TTL_SECONDS = 300


class InquiryCategory(enum.StrEnum):
    """Labels the classifier is allowed to produce.

    The values are the wire spelling; nothing outside this set may reach the
    rest of the system.
    """

    BILLING = "billing"
    SALES = "sales"
    TECHNICAL_SUPPORT = "technical_support"
    SHIPPING = "shipping"
    COMPLAINT = "complaint"
    OTHER = "other"


#: The closed list in the order it is shown to the model.
INQUIRY_CATEGORIES: Final[tuple[InquiryCategory, ...]] = (
    InquiryCategory.BILLING,
    InquiryCategory.SALES,
    InquiryCategory.TECHNICAL_SUPPORT,
    InquiryCategory.SHIPPING,
    InquiryCategory.COMPLAINT,
    InquiryCategory.OTHER,
)

#: Returned when the model answers with anything outside the closed list.
UNKNOWN_INQUIRY_CATEGORY: Final = "unknown"


class ResolvedInquiryCategory(enum.StrEnum):
    """What a caller actually receives: a known label, or the honest fallback.

    ``unknown`` is a member here and deliberately not a member of
    ``InquiryCategory``: the model is never offered it, the API can always
    return it.
    """

    BILLING = "billing"
    SALES = "sales"
    TECHNICAL_SUPPORT = "technical_support"
    SHIPPING = "shipping"
    COMPLAINT = "complaint"
    OTHER = "other"
    UNKNOWN = UNKNOWN_INQUIRY_CATEGORY


def resolve_category(category: InquiryCategory) -> ResolvedInquiryCategory:
    """Widens a validated label into the type the API publishes."""
    return ResolvedInquiryCategory(category.value)


class CachePort(Protocol):
    """The slice of a cache backend the assistant needs.

    Declared structurally so this module never has to import an implementation,
    and so a unit test can hand it a dictionary.
    """

    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, keys: str | Sequence[str]) -> None: ...

    async def invalidate_prefix(self, prefix: str) -> None: ...


class NoopCache:
    """Cache that stores nothing.

    The default whenever no backend is wired in, so that a missing cache is a
    performance property rather than a branch every call site has to handle.
    """

    async def get(self, key: str) -> Any | None:  # noqa: ARG002
        return None

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Intentionally empty: nothing is stored."""

    async def delete(self, keys: str | Sequence[str]) -> None:
        """Intentionally empty: nothing is stored."""

    async def invalidate_prefix(self, prefix: str) -> None:
        """Intentionally empty: nothing is stored."""


class LoggerPort(Protocol):
    """The two levels this module ever emits.

    Structural again, so the provider factory and the HTTP provider can be
    handed a recording double instead of a configured logging stack.
    """

    def warning(self, event: str, **kwargs: Any) -> Any: ...

    def error(self, event: str, **kwargs: Any) -> Any: ...
