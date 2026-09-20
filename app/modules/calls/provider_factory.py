"""Which telephony provider the process runs on.

Every value has a safe default, and the safest default of all is "no address":
with nothing configured the offline stub is used and the module still works end
to end. That is what keeps a fresh checkout runnable without a vendor account.

The adapter layer is the same either way. Both providers are wrapped in the same
retry decorator, with the same timeout and the same backoff, so switching the
address changes where the calls come from and nothing about how failure is
handled.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger
from app.modules.calls.http_provider import (
    CallTransport,
    HttpCallProvider,
    HttpCallProviderOptions,
)
from app.modules.calls.provider import (
    DEFAULT_PROVIDER_BACKOFF_MS,
    DEFAULT_PROVIDER_MAX_ATTEMPTS,
    DEFAULT_PROVIDER_TIMEOUT_MS,
    CallProvider,
    RetryOptions,
    with_retry,
)
from app.modules.calls.stub_provider import create_stub_call_provider

__all__ = [
    "DEFAULT_CALL_SYNC_BATCH_SIZE",
    "STUB_PROVIDER_WARNING",
    "CallProviderConfig",
    "create_call_provider",
]

#: How many records one sync may take. A deployment setting rather than a
#: client parameter: the import is bounded by what this system can absorb in a
#: request, not by what a caller would like.
DEFAULT_CALL_SYNC_BATCH_SIZE = 100

logger = get_logger("calls.provider")

STUB_PROVIDER_WARNING = (
    "No telephony provider configured; using the built-in offline stub. "
    "Synced calls are fixtures, not recorded traffic."
)


@dataclass(frozen=True, slots=True)
class CallProviderConfig:
    """Configuration the composition root supplies."""

    #: Absent or empty means "no provider configured" — the stub is used.
    base_url: str | None = None
    api_key: str | None = None
    timeout_ms: int = DEFAULT_PROVIDER_TIMEOUT_MS
    max_attempts: int = DEFAULT_PROVIDER_MAX_ATTEMPTS
    backoff_ms: int = DEFAULT_PROVIDER_BACKOFF_MS


def create_call_provider(
    config: CallProviderConfig | None = None,
    *,
    transport: CallTransport | None = None,
) -> CallProvider:
    """Chooses an implementation from configuration alone.

    ``transport`` is an injectable network seam for the HTTP provider; it is how
    a test exercises the endpoint path without a socket.
    """
    settings = config if config is not None else CallProviderConfig()

    provider: CallProvider
    if settings.base_url:
        provider = HttpCallProvider(
            HttpCallProviderOptions(
                base_url=settings.base_url,
                api_key=settings.api_key,
                timeout_ms=settings.timeout_ms,
                transport=transport,
            )
        )
    else:
        logger.warning(STUB_PROVIDER_WARNING)
        provider = create_stub_call_provider()

    return with_retry(
        provider,
        RetryOptions(max_attempts=settings.max_attempts, backoff_ms=settings.backoff_ms),
    )
