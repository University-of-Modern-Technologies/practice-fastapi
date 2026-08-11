"""Request body size guard.

An unbounded body is a denial-of-service vector: the process would buffer
whatever the client sends before any validation gets a chance to reject it. The
limit is enforced twice — once from the declared length, and once from what
actually arrives, because the declaration is under the client's control.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.handlers import error_response

_TOO_LARGE_MESSAGE = "Request body is too large"


class BodyLimitMiddleware:
    """Rejects bodies above ``max_bytes`` with HTTP 413."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            response = error_response(
                status_code=413,
                code="PAYLOAD_TOO_LARGE",
                message=_TOO_LARGE_MESSAGE,
            )
            await response(scope, receive, send)
            return

        received = 0
        over_limit = False

        async def receive_with_limit() -> Message:
            nonlocal received, over_limit
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    over_limit = True
                    # The body is truncated and marked complete so the
                    # application sees a short, invalid payload instead of
                    # continuing to buffer an oversized one.
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        sent_start = False

        async def send_guarded(message: Message) -> None:
            nonlocal sent_start
            if message["type"] == "http.response.start":
                sent_start = True
            await send(message)

        await self.app(scope, receive_with_limit, send_guarded)

        if over_limit and not sent_start:
            response = error_response(
                status_code=413,
                code="PAYLOAD_TOO_LARGE",
                message=_TOO_LARGE_MESSAGE,
            )
            await response(scope, receive, send)
