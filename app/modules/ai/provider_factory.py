"""Which provider the process runs on.

Every value has a safe default, and the safest default of all is "no endpoint":
with nothing configured the offline mock is used and the system still works end
to end. That is what keeps a fresh checkout runnable without a vendor account.
"""

from __future__ import annotations

import weakref
from collections.abc import MutableSet
from dataclasses import dataclass

from app.modules.ai.http_provider import (
    AiTransport,
    HttpAiProviderOptions,
    create_http_ai_provider,
)
from app.modules.ai.mock_provider import create_mock_ai_provider
from app.modules.ai.provider import AiProvider
from app.modules.ai.types import (
    DEFAULT_AI_CACHE_TTL_SECONDS,
    DEFAULT_AI_MAX_INPUT_CHARS,
    DEFAULT_AI_MAX_TOKENS,
    LoggerPort,
)

__all__ = [
    "DEFAULT_AI_CACHE_TTL_SECONDS",
    "DEFAULT_AI_MAX_INPUT_CHARS",
    "DEFAULT_AI_MAX_TOKENS",
    "AiConfig",
    "create_ai_provider",
]

MOCK_PROVIDER_WARNING = (
    "No AI endpoint configured; using the built-in offline mock provider. "
    "Responses are templated, not generated."
)


@dataclass(frozen=True, slots=True)
class AiConfig:
    """Configuration the composition root supplies."""

    #: Absent or empty means "no provider configured" — the mock is used.
    endpoint_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout_ms: int | None = None
    max_attempts: int | None = None
    #: Hard cap on the answer length requested from the provider.
    max_tokens: int | None = None
    #: Hard cap on user-supplied input, enforced before any prompt is built.
    max_input_chars: int | None = None
    cache_ttl_seconds: int | None = None


# The warning is emitted once per logger rather than once per process, so a
# long-running server does not repeat it and tests stay independent.
_warned_loggers: MutableSet[LoggerPort] = weakref.WeakSet()


def _warn_once(logger: LoggerPort) -> None:
    if logger in _warned_loggers:
        return
    _warned_loggers.add(logger)
    logger.warning(MOCK_PROVIDER_WARNING)


def create_ai_provider(
    config: AiConfig | None = None,
    logger: LoggerPort | None = None,
    transport: AiTransport | None = None,
) -> AiProvider:
    """Chooses an implementation from configuration alone.

    ``transport`` is an injectable network seam for the HTTP provider; it is how
    a test exercises the endpoint path without a socket.
    """
    settings = config or AiConfig()

    if not settings.endpoint_url:
        if logger is not None:
            _warn_once(logger)
        return create_mock_ai_provider()

    return create_http_ai_provider(
        HttpAiProviderOptions(
            endpoint_url=settings.endpoint_url,
            api_key=settings.api_key,
            model=settings.model,
            timeout_ms=settings.timeout_ms,
            max_attempts=settings.max_attempts,
            transport=transport,
            logger=logger,
        )
    )
