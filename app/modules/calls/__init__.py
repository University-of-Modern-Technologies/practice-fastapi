"""The call log: telephone traffic, and what it turned out to be about.

Records here are imported, not authored. The provider reports what happened on
the line; people then attach the meaning — the customer, the deal, the note that
explains why the conversation mattered. That division is why ``sync`` writes
only provider facts and ``PATCH`` writes only associations.

The import is idempotent by identity: ``externalId`` is unique, so running the
same batch again files nothing and reports it as skipped. Everything the module
needs in order to run — including the provider — is in this repository, so a
fresh checkout syncs, links and plays back with no account and no network.

Mount with ``create_calls_router()`` under ``/api/v1/calls``.
"""

from __future__ import annotations

from app.modules.calls.http_provider import (
    CallTransport,
    CallTransportRequest,
    CallTransportResponse,
    HttpCallProvider,
    HttpCallProviderOptions,
)
from app.modules.calls.provider import (
    CallProvider,
    CallProviderFetchRequest,
    ProviderCall,
    RetryableProviderError,
    RetryOptions,
    call_provider_unavailable_error,
    with_retry,
)
from app.modules.calls.provider_factory import (
    DEFAULT_CALL_SYNC_BATCH_SIZE,
    CallProviderConfig,
    create_call_provider,
)
from app.modules.calls.router import (
    CallsServiceDep,
    create_calls_router,
    get_call_provider,
    get_calls_service,
)
from app.modules.calls.schemas import (
    CallListParams,
    CallOut,
    CallRecordingOut,
    LinkCallRequest,
    SyncCallsOut,
    UpdateCallRequest,
)
from app.modules.calls.service import RECORDING_URL_TTL_SECONDS, CallsService, to_call_out
from app.modules.calls.stub_provider import (
    STUB_CALL_JOURNAL_SIZE,
    StubCallProvider,
    create_stub_call_provider,
    stub_journal,
)
from app.modules.calls.types import CallAccess, CallSortField

__all__ = [
    "DEFAULT_CALL_SYNC_BATCH_SIZE",
    "RECORDING_URL_TTL_SECONDS",
    "STUB_CALL_JOURNAL_SIZE",
    "CallAccess",
    "CallListParams",
    "CallOut",
    "CallProvider",
    "CallProviderConfig",
    "CallProviderFetchRequest",
    "CallRecordingOut",
    "CallSortField",
    "CallTransport",
    "CallTransportRequest",
    "CallTransportResponse",
    "CallsService",
    "CallsServiceDep",
    "HttpCallProvider",
    "HttpCallProviderOptions",
    "LinkCallRequest",
    "ProviderCall",
    "RetryOptions",
    "RetryableProviderError",
    "StubCallProvider",
    "SyncCallsOut",
    "UpdateCallRequest",
    "call_provider_unavailable_error",
    "create_call_provider",
    "create_calls_router",
    "create_stub_call_provider",
    "get_call_provider",
    "get_calls_service",
    "stub_journal",
    "to_call_out",
    "with_retry",
]
