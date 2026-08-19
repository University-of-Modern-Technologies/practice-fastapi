"""The delivery provider integration: transport, retries, breaker and mapping.

The only entry point other layers need is
``create_configured_delivery_client()``; everything else in this package exists
so that the client can be built, tested and observed.
"""

from __future__ import annotations

from app.modules.integrations.delivery.circuit_breaker import (
    DEFAULT_COOLDOWN_MS,
    DEFAULT_FAILURE_THRESHOLD,
    CircuitBreaker,
    CircuitBreakerSnapshot,
)
from app.modules.integrations.delivery.client import (
    DeliveryClient,
    DeliveryClientOptions,
    parse_retry_after_ms,
)
from app.modules.integrations.delivery.errors import (
    DELIVERY_INVALID_RESPONSE,
    DELIVERY_REJECTED,
    DELIVERY_TIMEOUT,
    DELIVERY_UNAVAILABLE,
)
from app.modules.integrations.delivery.factory import (
    DEFAULT_QUOTE_CACHE_TTL_SECONDS,
    DeliveryIntegrationConfig,
    create_configured_delivery_client,
)
from app.modules.integrations.delivery.schemas import UpstreamQuote, UpstreamShipment
from app.modules.integrations.delivery.stub_transport import StubDeliveryTransport
from app.modules.integrations.delivery.transport import (
    DeliveryTransport,
    DeliveryTransportRequest,
    DeliveryTransportResponse,
    HttpDeliveryTransport,
    TransportTimeoutError,
)

__all__ = [
    "DEFAULT_COOLDOWN_MS",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_QUOTE_CACHE_TTL_SECONDS",
    "DELIVERY_INVALID_RESPONSE",
    "DELIVERY_REJECTED",
    "DELIVERY_TIMEOUT",
    "DELIVERY_UNAVAILABLE",
    "CircuitBreaker",
    "CircuitBreakerSnapshot",
    "DeliveryClient",
    "DeliveryClientOptions",
    "DeliveryIntegrationConfig",
    "DeliveryTransport",
    "DeliveryTransportRequest",
    "DeliveryTransportResponse",
    "HttpDeliveryTransport",
    "StubDeliveryTransport",
    "TransportTimeoutError",
    "UpstreamQuote",
    "UpstreamShipment",
    "create_configured_delivery_client",
    "parse_retry_after_ms",
]
