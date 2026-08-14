"""The retry and validation policy of the endpoint-backed provider.

A fake transport stands in for the network, so every case below — a timeout, a
5xx, a 4xx, a payload that violates the contract — is exercised deterministically
and without a socket.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.errors import AppError
from app.modules.ai.http_provider import (
    AiTransportRequest,
    AiTransportResponse,
    HttpAiProviderOptions,
    create_http_ai_provider,
)
from app.modules.ai.provider import (
    AI_INVALID_RESPONSE,
    AI_TIMEOUT,
    AI_UNAVAILABLE,
    AiCompletionRequest,
    AiProvider,
)

ENDPOINT = "https://example.invalid/complete"
REQUEST = AiCompletionRequest(system="sys", prompt="p", max_tokens=32)


class FakeTransport:
    """Replays a script and records every body it was asked to send."""

    def __init__(self, script: list[AiTransportResponse | Exception]) -> None:
        self._script = script
        self.calls = 0
        self.bodies: list[Any] = []

    async def send(self, request: AiTransportRequest) -> AiTransportResponse:
        self.bodies.append(request.body)
        # The last entry repeats, so a script does not have to spell out every
        # attempt of a retrying provider.
        entry = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        if isinstance(entry, Exception):
            raise entry
        return entry


def provider_for(transport: FakeTransport, max_attempts: int = 2) -> AiProvider:
    async def no_delay(milliseconds: int) -> None:
        """The backoff is not what these tests are about."""

    return create_http_ai_provider(
        HttpAiProviderOptions(
            endpoint_url=ENDPOINT,
            transport=transport,
            max_attempts=max_attempts,
            delay=no_delay,
        )
    )


async def code_of(provider: AiProvider) -> str:
    with pytest.raises(AppError) as failure:
        await provider.complete(REQUEST)
    return failure.value.code


async def test_returns_the_validated_completion_text() -> None:
    provider = provider_for(FakeTransport([AiTransportResponse(200, {"text": "hello"})]))

    assert await provider.complete(REQUEST) == "hello"


async def test_forwards_the_bounded_token_budget_to_the_endpoint() -> None:
    transport = FakeTransport([AiTransportResponse(200, {"text": "hello"})])

    await provider_for(transport).complete(REQUEST)

    assert transport.bodies[0] == {"system": "sys", "prompt": "p", "max_tokens": 32}


async def test_includes_the_model_only_when_one_is_configured() -> None:
    transport = FakeTransport([AiTransportResponse(200, {"text": "hello"})])
    provider = create_http_ai_provider(
        HttpAiProviderOptions(endpoint_url=ENDPOINT, model="tiny-1", transport=transport)
    )

    await provider.complete(REQUEST)

    assert transport.bodies[0]["model"] == "tiny-1"


async def test_retries_a_5xx_and_then_succeeds() -> None:
    transport = FakeTransport(
        [AiTransportResponse(500, None), AiTransportResponse(200, {"text": "hello"})]
    )

    assert await provider_for(transport).complete(REQUEST) == "hello"
    assert transport.calls == 2


async def test_retries_a_429() -> None:
    transport = FakeTransport(
        [AiTransportResponse(429, None), AiTransportResponse(200, {"text": "hello"})]
    )

    assert await provider_for(transport).complete(REQUEST) == "hello"
    assert transport.calls == 2


async def test_does_not_retry_a_400() -> None:
    transport = FakeTransport([AiTransportResponse(400, {"error": "bad prompt"})])

    assert await code_of(provider_for(transport)) == AI_UNAVAILABLE
    assert transport.calls == 1


async def test_translates_an_exhausted_timeout_into_ai_timeout() -> None:
    transport = FakeTransport([TimeoutError("aborted")])

    assert await code_of(provider_for(transport)) == AI_TIMEOUT
    assert transport.calls == 2


async def test_a_connection_failure_is_reported_as_unavailable() -> None:
    transport = FakeTransport([OSError("connection refused")])

    assert await code_of(provider_for(transport)) == AI_UNAVAILABLE
    assert transport.calls == 2


async def test_rejects_a_payload_that_does_not_match_the_contract() -> None:
    transport = FakeTransport([AiTransportResponse(200, {"output": "wrong field"})])

    assert await code_of(provider_for(transport)) == AI_INVALID_RESPONSE
    # A contract violation is not transient, so it is not retried.
    assert transport.calls == 1


async def test_rejects_an_empty_completion() -> None:
    transport = FakeTransport([AiTransportResponse(200, {"text": ""})])

    assert await code_of(provider_for(transport)) == AI_INVALID_RESPONSE


async def test_a_single_attempt_is_honoured() -> None:
    transport = FakeTransport([AiTransportResponse(503, None)])

    assert await code_of(provider_for(transport, max_attempts=1)) == AI_UNAVAILABLE
    assert transport.calls == 1
