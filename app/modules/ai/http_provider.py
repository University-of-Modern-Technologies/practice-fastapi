"""Talks to a configured completion endpoint.

Used only when the composition root supplies an endpoint URL; otherwise the mock
provider is the default. The transport is a seam rather than a hard-wired HTTP
client: production wires one over ``httpx``, tests wire a fake, and no test in
this module ever opens a socket.

The retry policy is deliberately narrow. A refused connection, a timeout, a 429
and a 5xx are transient and worth repeating with a growing pause. A 4xx means
our request was wrong, and repeating a wrong request changes nothing. A payload
that violates the contract is not transient either. The single-attempt provider
below decides which is which; `retry_provider.with_retry` decides how many
attempts to spend on it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.modules.ai.provider import (
    AiCompletionRequest,
    AiInvalidResponseError,
    AiProvider,
    AiTimeoutError,
    AiUnavailableError,
)
from app.modules.ai.retry_provider import RetryableAiError, RetryOptions, with_retry
from app.modules.ai.types import LoggerPort

__all__ = [
    "DEFAULT_AI_BACKOFF_MS",
    "DEFAULT_AI_MAX_ATTEMPTS",
    "DEFAULT_AI_TIMEOUT_MS",
    "HTTP_AI_PROVIDER_NAME",
    "AiCompletionPayload",
    "AiTransport",
    "AiTransportRequest",
    "AiTransportResponse",
    "HttpAiProvider",
    "HttpAiProviderOptions",
    "create_http_ai_provider",
]

HTTP_AI_PROVIDER_NAME = "http"

DEFAULT_AI_TIMEOUT_MS = 10_000
DEFAULT_AI_MAX_ATTEMPTS = 2
DEFAULT_AI_BACKOFF_MS = 250

MAX_COMPLETION_LENGTH = 20_000

_HTTP_OK = 200
_HTTP_MULTIPLE_CHOICES = 300
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR = 500

_MILLISECONDS_PER_SECOND = 1000


@dataclass(frozen=True, slots=True)
class AiTransportRequest:
    """One outbound call, with the budget it must finish inside."""

    body: Any
    timeout_ms: int


@dataclass(frozen=True, slots=True)
class AiTransportResponse:
    """What came back, before any interpretation."""

    status: int
    body: Any


class AiTransport(Protocol):
    """Seam between the HTTP provider and the network."""

    async def send(self, request: AiTransportRequest) -> AiTransportResponse: ...


class AiCompletionPayload(BaseModel):
    """Minimal contract we require of the endpoint; anything else is rejected."""

    text: str = Field(min_length=1, max_length=MAX_COMPLETION_LENGTH)


class HttpxAiTransport:
    """The production seam: one request over HTTP, no interpretation."""

    def __init__(self, endpoint_url: str, api_key: str | None = None) -> None:
        self._endpoint_url = endpoint_url
        self._api_key = api_key

    async def send(self, request: AiTransportRequest) -> AiTransportResponse:
        headers = {"accept": "application/json", "content-type": "application/json"}
        if self._api_key is not None:
            headers["authorization"] = f"Bearer {self._api_key}"

        timeout = request.timeout_ms / _MILLISECONDS_PER_SECOND
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(self._endpoint_url, json=request.body, headers=headers)

        try:
            # An empty or unparseable body is reported as "no body" rather than
            # raised: the status code is still worth acting on.
            body = response.json() if response.content else None
        except ValueError:
            body = None
        return AiTransportResponse(status=response.status_code, body=body)


def _is_timeout_error(error: BaseException) -> bool:
    """Separates "took too long" from "could not be reached at all"."""
    return isinstance(error, httpx.TimeoutException | TimeoutError)


@dataclass(frozen=True, slots=True)
class HttpAiProviderOptions:
    """Everything the endpoint-backed provider can be told.

    Grouped into one value rather than a long parameter list: the transport, the
    logger and the delay are seams for tests, and the rest is configuration, so
    call sites read better naming what they set than counting positions.
    """

    endpoint_url: str
    api_key: str | None = None
    model: str | None = None
    timeout_ms: int | None = None
    max_attempts: int | None = None
    backoff_ms: int | None = None
    #: Injectable network seam; ``None`` builds the httpx-backed one.
    transport: AiTransport | None = None
    logger: LoggerPort | None = None
    #: Injectable sleep, so a test does not have to wait out a real backoff.
    delay: Callable[[int], Awaitable[None]] | None = None


class HttpAiProvider:
    """A single request/response round trip against the completion endpoint.

    Sends the request, then classifies and validates the outcome. Transient
    failures (timeout, network error, 429, 5xx) are reported to the caller as
    a `RetryableAiError` rather than retried here — retrying is the concern
    of `retry_provider.with_retry`, not of talking to the wire.
    """

    name = HTTP_AI_PROVIDER_NAME

    def __init__(self, options: HttpAiProviderOptions) -> None:
        self._model = options.model
        self._timeout_ms = (
            DEFAULT_AI_TIMEOUT_MS if options.timeout_ms is None else options.timeout_ms
        )
        self._transport = options.transport or HttpxAiTransport(
            options.endpoint_url, options.api_key
        )
        self._logger = options.logger

    def _request_body(self, request: AiCompletionRequest) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if self._model is not None:
            body["model"] = self._model
        body["system"] = request.system
        body["prompt"] = request.prompt
        body["max_tokens"] = request.max_tokens
        return body

    async def _send(self, request: AiCompletionRequest) -> AiTransportResponse:
        try:
            return await self._transport.send(
                AiTransportRequest(body=self._request_body(request), timeout_ms=self._timeout_ms)
            )
        except Exception as error:
            failure = AiTimeoutError() if _is_timeout_error(error) else AiUnavailableError()
            if self._logger is not None:
                self._logger.warning("AI completion request failed", err=repr(error))
            raise RetryableAiError(failure) from error

    def _read(self, response: AiTransportResponse) -> str:
        if response.status == _HTTP_TOO_MANY_REQUESTS or response.status >= _HTTP_SERVER_ERROR:
            if self._logger is not None:
                self._logger.warning(
                    "AI endpoint returned a transient error", status=response.status
                )
            raise RetryableAiError(AiUnavailableError())

        # A 4xx means our request was wrong; repeating it changes nothing.
        if response.status < _HTTP_OK or response.status >= _HTTP_MULTIPLE_CHOICES:
            if self._logger is not None:
                self._logger.warning("AI endpoint rejected the request", status=response.status)
            raise AiUnavailableError()

        try:
            payload = AiCompletionPayload.model_validate(response.body)
        except ValidationError as error:
            # The raw payload stays in our logs and never reaches the caller.
            if self._logger is not None:
                self._logger.error("AI endpoint returned an invalid payload", issues=error.errors())
            raise AiInvalidResponseError() from error
        return payload.text

    async def complete(self, request: AiCompletionRequest) -> str:
        return self._read(await self._send(request))


def create_http_ai_provider(options: HttpAiProviderOptions) -> AiProvider:
    """Builds the endpoint-backed provider, wrapped with its retry policy."""
    max_attempts = DEFAULT_AI_MAX_ATTEMPTS if options.max_attempts is None else options.max_attempts
    backoff_ms = DEFAULT_AI_BACKOFF_MS if options.backoff_ms is None else options.backoff_ms
    return with_retry(
        HttpAiProvider(options),
        RetryOptions(
            max_attempts=max_attempts,
            backoff_ms=backoff_ms,
            logger=options.logger,
            delay=options.delay,
        ),
    )
