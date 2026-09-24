"""Talks to a configured telephony endpoint.

Used only when the composition root supplies a provider address; otherwise the
stub is the default. The transport is a seam rather than a hard-wired HTTP
client: production wires one over ``httpx``, tests wire a fake, and no test in
this module ever opens a socket.

Whatever comes back is validated before a single row is written. A telephony
provider is somebody else's system, and the one thing worse than a failed sync
is a successful one that fills the call log with numbers no schema ever checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Protocol

import httpx
from pydantic import AwareDatetime, Field, TypeAdapter, ValidationError

from app.core.logging import get_logger
from app.core.responses import CamelModel
from app.db.enums import CallDirection, CallDisposition
from app.modules.calls.provider import (
    DEFAULT_PROVIDER_TIMEOUT_MS,
    MAX_PROVIDER_BATCH_SIZE,
    CallProviderFetchRequest,
    ProviderCall,
    RetryableProviderError,
    call_provider_unavailable_error,
)
from app.modules.calls.schemas import PhoneNumber
from app.modules.calls.types import (
    MAX_EXTERNAL_ID_LENGTH,
    MAX_RECORDING_URL_LENGTH,
)

__all__ = [
    "CALLS_BATCH_PATH",
    "HTTP_CALL_PROVIDER_NAME",
    "CallPayload",
    "CallTransport",
    "CallTransportRequest",
    "CallTransportResponse",
    "HttpCallProvider",
    "HttpCallProviderOptions",
    "HttpxCallTransport",
]

logger = get_logger("calls.provider")

HTTP_CALL_PROVIDER_NAME = "http"

#: The one path this module asks of the provider.
CALLS_BATCH_PATH = "/v1/calls"

_HTTP_OK = 200
_HTTP_MULTIPLE_CHOICES = 300
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR = 500

_MILLISECONDS_PER_SECOND = 1000


@dataclass(frozen=True, slots=True)
class CallTransportRequest:
    """One outbound call, with the budget it must finish inside."""

    path: str
    limit: int
    timeout_ms: int


@dataclass(frozen=True, slots=True)
class CallTransportResponse:
    """What came back, before any interpretation."""

    status: int
    body: Any


class CallTransport(Protocol):
    """Seam between the provider and the network."""

    async def send(self, request: CallTransportRequest) -> CallTransportResponse: ...


class CallPayload(CamelModel):
    """One call as the endpoint is documented to report it.

    The bounds repeat the column widths on purpose: a value the database would
    refuse must be refused here, where it is still one upstream's bad answer
    rather than a failed transaction halfway through a batch.

    This is also the one place a telephone number is checked at all. No request
    body in this module carries one — the numbers are always the provider's
    statement — so the boundary with the provider is where E.164 is enforced.
    """

    external_id: str = Field(min_length=1, max_length=MAX_EXTERNAL_ID_LENGTH)
    direction: CallDirection
    disposition: CallDisposition
    from_number: PhoneNumber
    to_number: PhoneNumber
    # A zone is required rather than assumed: an instant without one means a
    # different moment in every office that reports it.
    started_at: AwareDatetime
    duration_seconds: int = Field(ge=0)
    recording_url: str | None = Field(default=None, max_length=MAX_RECORDING_URL_LENGTH)


#: The endpoint answers with a bare array of records, under the wire names the
#: provider is documented to use. Bounded on the way in: one that offers more
#: than this is misbehaving, and importing an unbounded batch inside a single
#: request is how a sync becomes an outage of its own making.
_BATCH_ADAPTER: TypeAdapter[list[CallPayload]] = TypeAdapter(
    Annotated[list[CallPayload], Field(max_length=MAX_PROVIDER_BATCH_SIZE)]
)


class HttpxCallTransport:
    """The production seam: one request over HTTP, no interpretation."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def send(self, request: CallTransportRequest) -> CallTransportResponse:
        headers = {"accept": "application/json"}
        if self._api_key is not None:
            headers["authorization"] = f"Bearer {self._api_key}"

        timeout = request.timeout_ms / _MILLISECONDS_PER_SECOND
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{self._base_url}{request.path}",
                params={"limit": request.limit},
                headers=headers,
            )

        try:
            # An empty or unparseable body is reported as "no body" rather than
            # raised: the status code is still worth acting on.
            body = response.json() if response.content else None
        except ValueError:
            body = None
        return CallTransportResponse(status=response.status_code, body=body)


@dataclass(frozen=True, slots=True)
class HttpCallProviderOptions:
    """Everything the endpoint-backed provider can be told.

    Grouped into one value rather than a long parameter list: the transport is a
    seam for tests and the rest is configuration, so call sites read better
    naming what they set than counting positions.
    """

    base_url: str
    api_key: str | None = None
    timeout_ms: int | None = None
    #: Injectable network seam; ``None`` builds the httpx-backed one.
    transport: CallTransport | None = None


class HttpCallProvider:
    """A single request/response round trip against the telephony endpoint.

    Sends the request, then classifies and validates the outcome. Transient
    failures are reported as a `RetryableProviderError` rather than retried
    here — how many attempts to spend is the decorator's concern, not that of
    talking to the wire.
    """

    name = HTTP_CALL_PROVIDER_NAME

    def __init__(self, options: HttpCallProviderOptions) -> None:
        self._timeout_ms = (
            DEFAULT_PROVIDER_TIMEOUT_MS if options.timeout_ms is None else options.timeout_ms
        )
        self._transport = options.transport or HttpxCallTransport(options.base_url, options.api_key)

    async def _send(self, request: CallProviderFetchRequest) -> CallTransportResponse:
        try:
            return await self._transport.send(
                CallTransportRequest(
                    path=CALLS_BATCH_PATH, limit=request.limit, timeout_ms=self._timeout_ms
                )
            )
        except Exception as error:
            # A timeout or a socket error says nothing about our request and
            # everything about the dependency, so it is worth repeating.
            logger.warning("Telephony request failed", err=repr(error))
            raise RetryableProviderError(call_provider_unavailable_error()) from error

    def _read(self, response: CallTransportResponse) -> list[ProviderCall]:
        if response.status == _HTTP_TOO_MANY_REQUESTS or response.status >= _HTTP_SERVER_ERROR:
            logger.warning("Telephony endpoint returned a transient error", status=response.status)
            raise RetryableProviderError(call_provider_unavailable_error())

        # A 4xx means our request was wrong; repeating it changes nothing.
        if response.status < _HTTP_OK or response.status >= _HTTP_MULTIPLE_CHOICES:
            logger.warning("Telephony endpoint rejected the request", status=response.status)
            raise call_provider_unavailable_error()

        try:
            records = _BATCH_ADAPTER.validate_python(response.body)
        except ValidationError as error:
            # The raw payload stays in our logs and never reaches the caller: it
            # is third-party text of unknown shape.
            logger.error("Telephony endpoint returned an invalid payload", issues=error.errors())
            raise call_provider_unavailable_error() from error

        return [
            ProviderCall(
                external_id=item.external_id,
                direction=item.direction,
                disposition=item.disposition,
                from_number=item.from_number,
                to_number=item.to_number,
                started_at=item.started_at,
                duration_seconds=item.duration_seconds,
                recording_url=item.recording_url,
            )
            for item in records
        ]

    async def fetch_calls(self, request: CallProviderFetchRequest) -> list[ProviderCall]:
        return self._read(await self._send(request))
