"""A named bundle of stand-in-or-real implementations, chosen together.

Before this module existed, the AI provider looked at ``ai_endpoint_url``, the
delivery client looked at ``delivery_base_url`` and the cache always dialled
Redis — three independent decisions that could disagree, so a demo could end
up with a live AI provider, a stubbed delivery transport and a cache nobody
noticed was still real. ``create_infra_stack`` makes that one decision instead
of three.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from app.cache import CacheRedis, CacheService, NoopCacheService
from app.core.settings import Settings
from app.modules.ai import AiConfig, AiProvider, create_ai_provider
from app.modules.calls import CallProviderConfig
from app.modules.integrations import (
    DeliveryClient,
    DeliveryIntegrationConfig,
    create_configured_delivery_client,
)

InfraProfile = Literal["offline", "live"]

#: `live` reproduces today's behaviour exactly: every dependency still decides
#: for itself from its own setting, falling back to its own stand-in when that
#: setting is absent. It is the default so a fresh checkout — or any
#: deployment that has never heard of `infra_profile` — boots the same way it
#: always has.
DEFAULT_INFRA_PROFILE: InfraProfile = "live"


def resolve_infra_profile(raw: InfraProfile | None) -> InfraProfile:
    """An unset value keeps the default rather than failing the boot."""
    return raw or DEFAULT_INFRA_PROFILE


@dataclass(slots=True)
class InfraStack:
    """The three swappable dependencies, built together as one decision."""

    profile: InfraProfile
    ai_config: AiConfig
    call_provider_config: CallProviderConfig
    ai_provider: AiProvider
    delivery_client: DeliveryClient
    cache: CacheService | NoopCacheService


def create_infra_stack(
    settings: Settings, redis: CacheRedis, logger: structlog.stdlib.BoundLogger
) -> InfraStack:
    """Builds the three swappable dependencies as one decision instead of three.

    `offline` withholds every per-component setting so each factory falls back
    to the stand-in it already had; `live` forwards the configured settings
    and leaves each factory to fall back exactly as it always has when a
    setting is absent. Neither branch changes what ``create_ai_provider``,
    ``create_configured_delivery_client`` or ``CacheService`` do — this only
    decides what gets handed to them.
    """
    profile = resolve_infra_profile(settings.infra_profile)
    offline = profile == "offline"

    # Only the setting that *selects* an implementation is withheld: the
    # tuning knobs below it (timeouts, retry counts, cache TTLs) belong to the
    # service using the dependency, not to the choice of stand-in-or-real, so
    # they stay in effect no matter which profile is active.
    ai_config = AiConfig(
        endpoint_url=None if offline else settings.ai_endpoint_url,
        api_key=None if offline else settings.ai_api_key,
        model=None if offline else settings.ai_model,
        timeout_ms=settings.ai_timeout_ms,
        max_attempts=settings.ai_max_attempts,
        max_tokens=settings.ai_max_tokens,
        max_input_chars=settings.ai_max_input_chars,
        cache_ttl_seconds=settings.ai_cache_ttl_seconds,
    )

    call_provider_config = CallProviderConfig(
        base_url=None if offline else settings.call_provider_base_url,
        api_key=None if offline else settings.call_provider_api_key,
        timeout_ms=settings.call_provider_timeout_ms,
        max_attempts=settings.call_provider_max_attempts,
        backoff_ms=settings.call_provider_backoff_ms,
    )

    delivery_config = DeliveryIntegrationConfig(
        base_url=None if offline else settings.delivery_base_url,
        api_key=None if offline else settings.delivery_api_key,
        timeout_ms=settings.delivery_timeout_ms,
        max_attempts=settings.delivery_max_attempts,
        base_backoff_ms=settings.delivery_base_backoff_ms,
        max_backoff_ms=settings.delivery_max_backoff_ms,
        failure_threshold=settings.delivery_failure_threshold,
        cooldown_ms=settings.delivery_cooldown_ms,
        quote_cache_ttl_seconds=settings.delivery_quote_cache_ttl_seconds,
    )

    return InfraStack(
        profile=profile,
        ai_config=ai_config,
        ai_provider=create_ai_provider(config=ai_config, logger=logger),
        call_provider_config=call_provider_config,
        delivery_client=create_configured_delivery_client(delivery_config),
        # Offline means no external store at all, not merely an unreachable
        # one: the noop cache never opens a socket, whereas a real Redis
        # client that failed to connect would still show up in logs and
        # readiness.
        cache=NoopCacheService() if offline else CacheService(redis, settings),
    )
