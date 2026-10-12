"""Wraps an `AiProvider` with retries for transient failures.

The wrapped provider decides, per attempt, whether a failure is worth
retrying by raising a `RetryableAiError`; everything else propagates on the
first attempt, unretried.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.errors import AppError
from app.modules.ai.provider import AiCompletionRequest, AiProvider, AiUnavailableError
from app.modules.ai.types import LoggerPort

__all__ = ["RetryableAiError", "RetryingAiProvider", "with_retry"]

_MILLISECONDS_PER_SECOND = 1000

#: Longest single pause between two attempts, however large the base.
MAX_RETRY_BACKOFF_MS = 5_000
#: Longest a completion may keep retrying, counted from its first attempt. The
#: caller is waiting on an HTTP request, and an answer of "unavailable" given
#: promptly serves them better than one given minutes later.
MAX_RETRY_TOTAL_MS = 30_000


async def _default_delay(milliseconds: int) -> None:
    await asyncio.sleep(milliseconds / _MILLISECONDS_PER_SECOND)


def _monotonic_ms() -> float:
    return time.monotonic() * _MILLISECONDS_PER_SECOND


class RetryableAiError(Exception):
    """Internal marker: this attempt failed in a way worth repeating."""

    def __init__(self, failure: AppError) -> None:
        super().__init__(failure.message)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class RetryOptions:
    max_attempts: int = 1
    backoff_ms: int = 0
    logger: LoggerPort | None = None
    #: Injectable sleep, so a test does not have to wait out a real backoff.
    delay: Callable[[int], Awaitable[None]] | None = None
    #: Injectable clock for the total retry budget.
    now_ms: Callable[[], float] | None = None


class RetryingAiProvider:
    """An `AiProvider` that retries a wrapped provider's transient failures."""

    def __init__(self, provider: AiProvider, options: RetryOptions | None = None) -> None:
        self._provider = provider
        self._options = options or RetryOptions()
        self._attempts = max(1, self._options.max_attempts)
        self._delay = self._options.delay or _default_delay
        self._now_ms = self._options.now_ms or _monotonic_ms

    @property
    def name(self) -> str:
        return self._provider.name

    async def complete(self, request: AiCompletionRequest) -> str:
        last_failure: AppError = AiUnavailableError()
        started_at = self._now_ms()

        for attempt in range(1, self._attempts + 1):
            try:
                return await self._provider.complete(request)
            except RetryableAiError as transient:
                last_failure = transient.failure
                if self._options.logger is not None:
                    self._options.logger.warning(
                        "AI completion attempt failed; retrying", attempt=attempt
                    )
                if attempt == self._attempts:
                    raise last_failure from transient
                wait = min(MAX_RETRY_BACKOFF_MS, self._options.backoff_ms * 2 ** (attempt - 1))
                # Another attempt that could only start past the budget is not made.
                if self._now_ms() - started_at + wait > MAX_RETRY_TOTAL_MS:
                    raise last_failure from transient
                await self._delay(wait)

        raise last_failure


def with_retry(provider: AiProvider, options: RetryOptions | None = None) -> AiProvider:
    """Builds the retrying decorator around `provider`."""
    return RetryingAiProvider(provider, options)
