"""Outbound integrations: everything this system asks of somebody else's.

Today that is one delivery provider. The module exists to keep a third party's
bad day from becoming ours: timeouts, retries, a circuit breaker and strict
validation of whatever comes back all live behind three plain method calls.

Mount with ``create_integrations_router()`` under ``/api/v1/integrations``.
"""

from __future__ import annotations

from app.modules.integrations.delivery import (
    DeliveryClient,
    DeliveryIntegrationConfig,
    create_configured_delivery_client,
)
from app.modules.integrations.router import (
    create_integrations_router,
    get_delivery_client,
    get_integrations_service,
)
from app.modules.integrations.schemas import (
    CreateShipmentData,
    CreateShipmentRequest,
    DeliveryAddress,
    DeliveryParcel,
    QuoteRequest,
    QuoteRequestData,
)
from app.modules.integrations.service import IntegrationsService, quote_cache_key
from app.modules.integrations.types import (
    CircuitState,
    DeliveryHealthDto,
    DeliveryQuoteDto,
    ShipmentDto,
    ShipmentStatus,
    TransportKind,
)

__all__ = [
    "CircuitState",
    "CreateShipmentData",
    "CreateShipmentRequest",
    "DeliveryAddress",
    "DeliveryClient",
    "DeliveryHealthDto",
    "DeliveryIntegrationConfig",
    "DeliveryParcel",
    "DeliveryQuoteDto",
    "IntegrationsService",
    "QuoteRequest",
    "QuoteRequestData",
    "ShipmentDto",
    "ShipmentStatus",
    "TransportKind",
    "create_configured_delivery_client",
    "create_integrations_router",
    "get_delivery_client",
    "get_integrations_service",
    "quote_cache_key",
]
