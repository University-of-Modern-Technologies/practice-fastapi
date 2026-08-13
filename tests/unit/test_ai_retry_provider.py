"""The retrying decorator around an `AiProvider`, independent of HTTP.

A hand-written inner provider stands in for `HttpAiProvider`, so what is
tested here is purely the retry/backoff policy: how many attempts a
transient failure gets, and that a non-retryable failure gets exactly one.
"""

from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.modules.ai.provider import AiCompletionRequest, AiTimeoutError, AiUnavailableError
from app.modules.ai.retry_provider import RetryableAiError, RetryingAiProvider, RetryOptions

REQUEST = AiCompletionRequest(system="sys", prompt="p", max_tokens=16)


class ScriptedProvider:
    name = "inner"

    def __init__(self, script: list[str | Exception]) -> None:
        self._script = script
        self.calls = 0

    async def complete(self, request: AiCompletionRequest) -> str:  # noqa: ARG002
        entry = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        if isinstance(entry, Exception):
            raise entry
        return entry


async def no_delay(milliseconds: int) -> None:
    pass


async def test_retries_a_transient_failure_and_returns_the_eventual_success() -> None:
    inner = ScriptedProvider([RetryableAiError(AiTimeoutError()), "done"])
    provider = RetryingAiProvider(inner, RetryOptions(max_attempts=2, delay=no_delay))

    assert await provider.complete(REQUEST) == "done"
    assert inner.calls == 2


async def test_propagates_a_non_retryable_failure_after_exactly_one_attempt() -> None:
    inner = ScriptedProvider([AiUnavailableError()])
    provider = RetryingAiProvider(inner, RetryOptions(max_attempts=3, delay=no_delay))

    with pytest.raises(AppError) as failure:
        await provider.complete(REQUEST)

    assert failure.value.code == "AI_UNAVAILABLE"
    assert inner.calls == 1


async def test_raises_the_last_transient_failure_once_attempts_are_exhausted() -> None:
    inner = ScriptedProvider([RetryableAiError(AiTimeoutError())])
    provider = RetryingAiProvider(inner, RetryOptions(max_attempts=2, delay=no_delay))

    with pytest.raises(AppError) as failure:
        await provider.complete(REQUEST)

    assert failure.value.code == "AI_TIMEOUT"
    assert inner.calls == 2


def test_preserves_the_wrapped_providers_name() -> None:
    inner = ScriptedProvider(["x"])
    assert RetryingAiProvider(inner).name == "inner"
