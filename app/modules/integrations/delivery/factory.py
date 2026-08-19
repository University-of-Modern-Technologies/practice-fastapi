"""Transport selection and client assembly.

Nothing here is read from the environment inside the module: the composition
root passes the configuration in, which is what makes the client testable and
the defaults honest.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger
from app.modules.integrations.delivery.circuit_breaker import (
    DEFAULT_COOLDOWN_MS,
    DEFAULT_FAILURE_THRESHOLD,
)
from app.modules.integrations.delivery.client import (
    DEFAULT_BASE_BACKOFF_MS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_BACKOFF_MS,
    DEFAULT_TIMEOUT_MS,
    DeliveryClient,
    DeliveryClientOptions,
)
from app.modules.integrations.delivery.stub_transport import StubDeliveryTransport
from app.modules.integrations.delivery.transport import (
    DeliveryTransport,
    HttpDeliveryTransport,
)
from app.modules.integrations.types import TransportKind

__all__ = [
    "DEFAULT_QUOTE_CACHE_TTL_SECONDS",
    "DeliveryIntegrationConfig",
    "create_configured_delivery_client",
]

logger = get_logger("integrations.delivery")

DEFAULT_QUOTE_CACHE_TTL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class DeliveryIntegrationConfig:
    """Everything the integration needs from the outside."""

    #: Absent means "no real provider configured" — the stub transport is used.
    base_url: str | None = None
    api_key: str | None = None
    timeout_ms: float = DEFAULT_TIMEOUT_MS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_backoff_ms: float = DEFAULT_BASE_BACKOFF_MS
    max_backoff_ms: float = DEFAULT_MAX_BACKOFF_MS
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    cooldown_ms: float = DEFAULT_COOLDOWN_MS
    #: How long a quote lookup may be served from cache.
    quote_cache_ttl_seconds: int = DEFAULT_QUOTE_CACHE_TTL_SECONDS


def create_configured_delivery_client(
    config: DeliveryIntegrationConfig | None = None,
    *,
    transport: DeliveryTransport | None = None,
) -> DeliveryClient:
    """Picks the transport and builds the client.

    With no base URL the in-repo stub is wired, so a fresh checkout runs end to
    end without any external account.
    """
    settings = config or DeliveryIntegrationConfig()
    selected: DeliveryTransport
    if transport is not None:
        selected = transport
    elif settings.base_url:
        selected = HttpDeliveryTransport(base_url=settings.base_url, api_key=settings.api_key)
    else:
        selected = StubDeliveryTransport()

    if selected.kind is TransportKind.STUB:
        logger.warning(
            "Delivery integration has no base URL configured; using the built-in stub transport"
        )

    return DeliveryClient(
        DeliveryClientOptions(
            transport=selected,
            timeout_ms=settings.timeout_ms,
            max_attempts=settings.max_attempts,
            base_backoff_ms=settings.base_backoff_ms,
            max_backoff_ms=settings.max_backoff_ms,
            failure_threshold=settings.failure_threshold,
            cooldown_ms=settings.cooldown_ms,
        )
    )
