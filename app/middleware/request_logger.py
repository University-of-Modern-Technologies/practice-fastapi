"""Access logging.

One line per request, emitted after the status is known, at a level that
reflects the outcome: server failures are errors, client failures are warnings,
everything else is informational.
"""

from __future__ import annotations

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger

logger = get_logger("http")

SERVER_ERROR_STATUS = 500
CLIENT_ERROR_STATUS = 400


def _level_for(status_code: int) -> str:
    if status_code >= SERVER_ERROR_STATUS:
        return "error"
    if status_code >= CLIENT_ERROR_STATUS:
        return "warning"
    return "info"


class RequestLoggerMiddleware:
    """Emits a structured access log line for every HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = time.perf_counter()
        status_code = 500

        async def send_with_logging(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_logging)
        finally:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            query = scope.get("query_string", b"").decode("latin-1")
            getattr(logger, _level_for(status_code))(
                "request completed",
                method=scope.get("method"),
                path=scope.get("path"),
                # The query string is logged separately from the path so a
                # future redaction rule can drop it without losing the route.
                query=query or None,
                status=status_code,
                durationMs=duration_ms,
            )
