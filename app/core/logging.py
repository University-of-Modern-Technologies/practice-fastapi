"""Structured logging.

Two rules are non-negotiable: every line carries the correlation id of the
request that produced it, and no line ever carries a credential. Both are
enforced by processors here rather than by discipline at each call site.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from app.core.settings import Settings
from app.middleware.request_id import get_request_id

REDACTED = "[REDACTED]"

#: An event payload is a log line, not a structure to walk exhaustively.
MAX_REDACTION_DEPTH = 6

# Matched against the lowercased key, as a substring: `passwordHash`,
# `refresh_token` and `authorization` all have to disappear.
_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "token",
    "secret",
    "authorization",
    "cookie",
    "credential",
    "api_key",
    "apikey",
)

_LEVEL_NAMES = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _redact(value: Any, depth: int = 0) -> Any:
    # Anything deeper than the bound is almost certainly a mistake at the
    # call site rather than something worth logging.
    if depth > MAX_REDACTION_DEPTH:
        return value
    if isinstance(value, MutableMapping):
        return {
            key: REDACTED if _is_sensitive(str(key)) else _redact(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, depth + 1) for item in value)
    return value


def redact_processor(
    _logger: object,
    _method: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Removes credentials from a log line before it reaches a renderer."""
    return {
        key: REDACTED if _is_sensitive(str(key)) else _redact(value)
        for key, value in event_dict.items()
    }


def request_id_processor(
    _logger: object,
    _method: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Attaches the correlation id of the in-flight request, when there is one."""
    request_id = get_request_id()
    if request_id is not None:
        event_dict.setdefault("requestId", request_id)
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Installs the processor chain. Safe to call more than once."""
    level = _LEVEL_NAMES[settings.log_level]

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    # uvicorn installs its own handlers; routing them through the root logger
    # keeps server and application lines in one format.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # The server's access log is silenced outright: the request logger
    # middleware already emits one line per request, and that one carries the
    # correlation id.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    access_logger.disabled = True

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        request_id_processor,
        redact_processor,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Human-readable output is a development convenience only; every other
    # environment emits one JSON object per line for the log pipeline.
    processors.append(
        structlog.dev.ConsoleRenderer(colors=True)
        if settings.app_env == "development"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.bind_contextvars(
        service="python-backend",
        environment=settings.app_env,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Returns a bound logger; the name becomes the ``logger`` field."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
