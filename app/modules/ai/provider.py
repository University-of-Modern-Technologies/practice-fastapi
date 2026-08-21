"""Provider-agnostic port for text completion.

Everything above this interface — prompt building, validation, caching — is
written once and works with the offline mock, with an HTTP endpoint, or with
whatever comes next. The port is deliberately tiny: no streaming, no tools, no
message history. A narrow port is a port that is easy to fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.errors import AppError

__all__ = [
    "AI_INPUT_TOO_LARGE",
    "AI_INVALID_RESPONSE",
    "AI_TIMEOUT",
    "AI_UNAVAILABLE",
    "AiCompletionRequest",
    "AiInputTooLargeError",
    "AiInvalidResponseError",
    "AiProvider",
    "AiTimeoutError",
    "AiUnavailableError",
]


@dataclass(frozen=True, slots=True)
class AiCompletionRequest:
    """One completion call, fully described."""

    #: Instructions from us. Never contains user-supplied text.
    system: str
    #: Task payload; user-supplied text appears here only inside delimiters.
    prompt: str
    #: Hard upper bound on the answer, so one call cannot run away with cost.
    max_tokens: int


class AiProvider(Protocol):
    """Anything that can turn a prompt into text."""

    @property
    def name(self) -> str:
        """Identifies the implementation in responses and logs."""

    async def complete(self, request: AiCompletionRequest) -> str: ...


AI_TIMEOUT = "AI_TIMEOUT"
AI_UNAVAILABLE = "AI_UNAVAILABLE"
AI_INVALID_RESPONSE = "AI_INVALID_RESPONSE"
AI_INPUT_TOO_LARGE = "AI_INPUT_TOO_LARGE"


class AiTimeoutError(AppError):
    """The provider was reachable but did not answer inside the budget."""

    def __init__(self) -> None:
        super().__init__("The assistant did not respond in time", 504, AI_TIMEOUT)


class AiUnavailableError(AppError):
    """The provider could not be reached, or refused the call outright."""

    def __init__(self) -> None:
        super().__init__("The assistant is temporarily unavailable", 503, AI_UNAVAILABLE)


class AiInvalidResponseError(AppError):
    """The provider answered with something outside the agreed contract.

    The raw payload stays in our logs and never reaches the caller: it is
    attacker-influenced text of unknown shape.
    """

    def __init__(self) -> None:
        super().__init__("The assistant returned an unexpected payload", 502, AI_INVALID_RESPONSE)


class AiInputTooLargeError(AppError):
    """The caller sent more text than this feature is willing to pay for."""

    def __init__(self, max_chars: int) -> None:
        super().__init__(f"Input exceeds the {max_chars} character limit", 400, AI_INPUT_TOO_LARGE)
