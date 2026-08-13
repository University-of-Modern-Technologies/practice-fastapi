"""Which provider the factory picks, and what it says about the choice."""

from __future__ import annotations

from typing import Any

from app.modules.ai.http_provider import HTTP_AI_PROVIDER_NAME
from app.modules.ai.mock_provider import MOCK_AI_PROVIDER_NAME
from app.modules.ai.provider_factory import AiConfig, create_ai_provider

ENDPOINT = "https://example.invalid/complete"


class RecordingLogger:
    """Counts what was logged, so "warns once" can be asserted at all."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def warning(self, event: str, **kwargs: Any) -> None:  # noqa: ARG002
        self.warnings.append(event)

    def error(self, event: str, **kwargs: Any) -> None:  # noqa: ARG002
        self.errors.append(event)


def test_uses_the_mock_provider_when_nothing_is_configured() -> None:
    assert create_ai_provider().name == MOCK_AI_PROVIDER_NAME
    assert create_ai_provider(config=AiConfig()).name == MOCK_AI_PROVIDER_NAME
    assert create_ai_provider(config=AiConfig(endpoint_url="")).name == MOCK_AI_PROVIDER_NAME


def test_warns_exactly_once_about_running_on_the_mock() -> None:
    logger = RecordingLogger()

    create_ai_provider(logger=logger)
    create_ai_provider(logger=logger)
    create_ai_provider(logger=logger)

    assert len(logger.warnings) == 1
    assert "offline mock provider" in logger.warnings[0]


def test_a_second_logger_is_warned_independently() -> None:
    first = RecordingLogger()
    second = RecordingLogger()

    create_ai_provider(logger=first)
    create_ai_provider(logger=second)

    # The warning is remembered per logger, not per process, so tests and
    # long-lived servers do not silence each other.
    assert len(first.warnings) == 1
    assert len(second.warnings) == 1


def test_uses_the_http_provider_once_an_endpoint_is_configured() -> None:
    provider = create_ai_provider(config=AiConfig(endpoint_url=ENDPOINT, api_key="k"))

    assert provider.name == HTTP_AI_PROVIDER_NAME


def test_does_not_warn_when_a_real_provider_is_configured() -> None:
    logger = RecordingLogger()

    create_ai_provider(config=AiConfig(endpoint_url=ENDPOINT), logger=logger)

    assert logger.warnings == []
