"""Provider-agnostic port for the telephony service.

Everything above this interface — deduplication, persistence, the audit trail —
is written once and works against the offline stub, against an HTTP endpoint, or
against whatever comes next. The port is deliberately tiny: one verb, one batch,
no pagination and no callbacks. A narrow port is a port that is easy to fake.

Every way the provider can fail collapses into a single reported failure, 502
``CALL_PROVIDER_UNAVAILABLE``. The distinction between a timeout, a refused
connection and a malformed payload matters to whoever is debugging the upstream,
and it belongs in the log line; to the caller of *our* API they are one fact —
the call log could not be refreshed right now — and every other endpoint of this
module keeps working while it holds.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.enums import CallDirection, CallDisposition
from app.modules.calls.types import CALL_PROVIDER_UNAVAILABLE

__all__ = [
    "DEFAULT_PROVIDER_BACKOFF_MS",
    "DEFAULT_PROVIDER_MAX_ATTEMPTS",
    "DEFAULT_PROVIDER_TIMEOUT_MS",
    "MAX_PROVIDER_BATCH_SIZE",
    "CallProvider",
    "CallProviderFetchRequest",
    "ProviderCall",
    "RetryOptions",
    "RetryableProviderError",
    "RetryingCallProvider",
    "call_provider_unavailable_error",
    "with_retry",
]

logger = get_logger("calls.provider")

DEFAULT_PROVIDER_TIMEOUT_MS = 5_000
DEFAULT_PROVIDER_MAX_ATTEMPTS = 3
DEFAULT_PROVIDER_BACKOFF_MS = 200

#: Upper bound on one batch. A provider that answers with more than this is
#: misbehaving, and importing an unbounded batch inside one request transaction
#: is how a sync turns into an outage of its own making.
MAX_PROVIDER_BATCH_SIZE = 500

_MILLISECONDS_PER_SECOND = 1000


def call_provider_unavailable_error() -> AppError:
    """The telephony provider could not be reached, or answered nonsense.

    The message is written for the caller of our API rather than for whoever is
    debugging the upstream: it never carries the base URL, the API key or the
    provider's own error text. Those stay in the log, on our side of the
    boundary.
    """
    return AppError(
        "The telephony provider is temporarily unavailable", 502, CALL_PROVIDER_UNAVAILABLE
    )


@dataclass(frozen=True, slots=True)
class ProviderCall:
    """One call as the provider reported it.

    Deliberately separate from the stored model and from the wire schema: the
    upstream is free to change its payload, and only the mapping layer has to
    follow. It carries no associations at all — the provider knows telephone
    numbers, not which contact or deal they belong to.
    """

    external_id: str
    direction: CallDirection
    disposition: CallDisposition
    from_number: str
    to_number: str
    started_at: datetime
    duration_seconds: int
    recording_url: str | None = None


@dataclass(frozen=True, slots=True)
class CallProviderFetchRequest:
    """One read of the provider's journal."""

    #: Upper bound on how many records one run may take. A deployment setting,
    #: never a client parameter: the import is bounded by what this system can
    #: absorb in a request, not by what a caller would like.
    limit: int


class CallProvider(Protocol):
    """Anything that can hand over a batch of calls."""

    @property
    def name(self) -> str:
        """Identifies the implementation in health output and logs."""

    async def fetch_calls(self, request: CallProviderFetchRequest) -> Sequence[ProviderCall]: ...


class RetryableProviderError(Exception):
    """Internal marker: this attempt failed in a way worth repeating.

    A provider decides, per attempt, whether its failure is transient. A refused
    connection, a timeout, a 429 and a 5xx are; a 4xx and a payload that
    violates the contract are not, because repeating a wrong request changes
    nothing.
    """

    def __init__(self, failure: AppError) -> None:
        super().__init__(failure.message)
        self.failure = failure


async def _default_delay(milliseconds: float) -> None:
    await asyncio.sleep(milliseconds / _MILLISECONDS_PER_SECOND)


@dataclass(frozen=True, slots=True)
class RetryOptions:
    """How much patience one fetch is allowed.

    The sleep is injectable for one reason: a retry policy that can only be
    observed in real time cannot be tested, and an untested retry policy is a
    way to take an upstream down twice as fast.
    """

    max_attempts: int = DEFAULT_PROVIDER_MAX_ATTEMPTS
    backoff_ms: int = DEFAULT_PROVIDER_BACKOFF_MS
    #: Injectable sleep, so a test does not have to wait out a real backoff.
    delay: Callable[[float], Awaitable[None]] | None = None


class RetryingCallProvider:
    """A `CallProvider` that repeats a wrapped provider's transient failures.

    Fetching a batch is a read, so replaying it is safe: the worst outcome is
    importing the same calls twice, and ``external_id`` already makes that a
    no-op. The pause between attempts grows exponentially so that a provider
    which is merely busy is not hammered while it recovers.
    """

    def __init__(self, provider: CallProvider, options: RetryOptions | None = None) -> None:
        self._provider = provider
        self._options = options if options is not None else RetryOptions()
        self._attempts = max(1, self._options.max_attempts)
        self._delay = self._options.delay if self._options.delay is not None else _default_delay

    @property
    def name(self) -> str:
        return self._provider.name

    async def fetch_calls(self, request: CallProviderFetchRequest) -> Sequence[ProviderCall]:
        last_failure: AppError = call_provider_unavailable_error()

        for attempt in range(1, self._attempts + 1):
            try:
                return await self._provider.fetch_calls(request)
            except RetryableProviderError as transient:
                last_failure = transient.failure
                logger.warning("Telephony fetch attempt failed; retrying", attempt=attempt)
                if attempt == self._attempts:
                    raise last_failure from transient
                await self._delay(self._options.backoff_ms * 2 ** (attempt - 1))

        raise last_failure


def with_retry(provider: CallProvider, options: RetryOptions | None = None) -> CallProvider:
    """Builds the retrying decorator around ``provider``."""
    return RetryingCallProvider(provider, options)
