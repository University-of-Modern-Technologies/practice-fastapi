"""Assistant features: deal summaries and inquiry classification.

Mount with ``create_ai_router()`` under ``/api/v1/ai``. With nothing configured
the module runs on a deterministic offline provider, so the endpoints answer on
a fresh checkout without a model vendor being involved.
"""

from __future__ import annotations

from app.modules.ai.http_provider import (
    HTTP_AI_PROVIDER_NAME,
    AiTransport,
    AiTransportRequest,
    AiTransportResponse,
    HttpAiProviderOptions,
    create_http_ai_provider,
)
from app.modules.ai.mock_provider import MOCK_AI_PROVIDER_NAME, create_mock_ai_provider
from app.modules.ai.provider import (
    AiCompletionRequest,
    AiInputTooLargeError,
    AiInvalidResponseError,
    AiProvider,
    AiTimeoutError,
    AiUnavailableError,
)
from app.modules.ai.provider_factory import AiConfig, create_ai_provider
from app.modules.ai.router import (
    AI_USE_PERMISSION,
    create_ai_router,
    get_ai_config,
    get_ai_provider,
    get_ai_service,
)
from app.modules.ai.schemas import (
    ClassifyInquiryRequest,
    DealSummaryOut,
    InquiryClassificationOut,
    SummariseDealRequest,
)
from app.modules.ai.service import AiService
from app.modules.ai.types import (
    INQUIRY_CATEGORIES,
    UNKNOWN_INQUIRY_CATEGORY,
    InquiryCategory,
    ResolvedInquiryCategory,
)

__all__ = [
    "AI_USE_PERMISSION",
    "HTTP_AI_PROVIDER_NAME",
    "INQUIRY_CATEGORIES",
    "MOCK_AI_PROVIDER_NAME",
    "UNKNOWN_INQUIRY_CATEGORY",
    "AiCompletionRequest",
    "AiConfig",
    "AiInputTooLargeError",
    "AiInvalidResponseError",
    "AiProvider",
    "AiService",
    "AiTimeoutError",
    "AiTransport",
    "AiTransportRequest",
    "AiTransportResponse",
    "AiUnavailableError",
    "ClassifyInquiryRequest",
    "DealSummaryOut",
    "HttpAiProviderOptions",
    "InquiryCategory",
    "InquiryClassificationOut",
    "ResolvedInquiryCategory",
    "SummariseDealRequest",
    "create_ai_provider",
    "create_ai_router",
    "create_http_ai_provider",
    "create_mock_ai_provider",
    "get_ai_config",
    "get_ai_provider",
    "get_ai_service",
]
