"""HTTP surface of the assistant.

Both endpoints are guarded by the single ``ai:use`` permission. They read no
domain tables: the facts a prompt is built from arrive in the request body,
already narrowed by whatever the caller was allowed to read when they fetched
the record. That keeps this module free of an authorization decision it is not
in a position to make correctly.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.core.logging import get_logger
from app.core.openapi import refusals
from app.core.responses import Envelope
from app.db.enums import PermissionScope
from app.modules.ai.provider import AiProvider
from app.modules.ai.provider_factory import AiConfig, create_ai_provider
from app.modules.ai.schemas import (
    ClassifyInquiryRequest,
    DealSummaryOut,
    InquiryClassificationOut,
    SummariseDealRequest,
)
from app.modules.ai.service import AiService
from app.modules.ai.types import CachePort, NoopCache
from app.modules.rbac.dependencies import require_permission

logger = get_logger("ai")

#: Resource used for every RBAC check in this module.
RESOURCE = "ai"
#: ``ai:use`` — the single permission guarding every assistant feature.
AI_USE_PERMISSION = "ai:use"


def get_ai_config(request: Request) -> AiConfig:
    """Assistant configuration published by the composition root, if any.

    Absent means "nothing configured", which the factory reads as "use the
    offline mock" — the feature answers on a fresh checkout either way.
    """
    config = getattr(request.app.state, "ai_config", None)
    return config if isinstance(config, AiConfig) else AiConfig()


AiConfigDep = Annotated[AiConfig, Depends(get_ai_config)]


def get_ai_provider(request: Request, config: AiConfigDep) -> AiProvider:
    """The provider this application runs on, built once and remembered.

    Building it per request would re-emit the "running on the mock" warning on
    every call and, for the HTTP provider, discard connection reuse.
    """
    provider = getattr(request.app.state, "ai_provider", None)
    if provider is None:
        provider = create_ai_provider(config=config, logger=logger)
        request.app.state.ai_provider = provider
    return cast(AiProvider, provider)


AiProviderDep = Annotated[AiProvider, Depends(get_ai_provider)]


def get_ai_cache(request: Request) -> CachePort:
    """The cache backend if one was wired in, otherwise a cache that stores nothing."""
    cache = getattr(request.app.state, "cache", None)
    if cache is None:
        return NoopCache()
    return cast(CachePort, cache)


AiCacheDep = Annotated[CachePort, Depends(get_ai_cache)]


def get_ai_service(provider: AiProviderDep, cache: AiCacheDep, config: AiConfigDep) -> AiService:
    return AiService(provider, cache, config)


AiServiceDep = Annotated[AiService, Depends(get_ai_service)]

#: The permission admits the caller; the breadth is not consulted further,
#: because nothing here selects rows to narrow.
UseAccess = Annotated[PermissionScope, Depends(require_permission(RESOURCE, "use"))]


def create_ai_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["AI"])

    @router.post(
        "/summaries/deal",
        summary="Скласти стислий переказ угоди",
        responses=refusals(401, 403, 502, 503, 504),
    )
    async def summarise_deal(
        payload: SummariseDealRequest,
        _access: UseAccess,
        service: AiServiceDep,
    ) -> Envelope[DealSummaryOut]:
        return Envelope(data=await service.summarise_deal(payload))

    @router.post(
        "/classify/inquiry",
        summary="Класифікувати звернення клієнта",
        responses=refusals(401, 403, 502, 503, 504),
    )
    async def classify_inquiry(
        payload: ClassifyInquiryRequest,
        _access: UseAccess,
        service: AiServiceDep,
    ) -> Envelope[InquiryClassificationOut]:
        return Envelope(data=await service.classify_inquiry(payload))

    return router
