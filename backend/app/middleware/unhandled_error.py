"""The 500 envelope, produced inside the middleware stack.

Starlette sends a handler registered for ``Exception`` to its outermost layer,
outside every user middleware. A 500 built there never passes back through the
security headers or CORS, so a browser sees a response without the hardening
headers and — for a cross-origin caller — cannot read it at all. The sibling
backend answers a crash like any other response; this layer makes that true
here as well, by turning the exception into the envelope where the outer layers
still see it.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.handlers import unhandled_error_response
from app.core.settings import Settings


class UnhandledErrorMiddleware:
    """Answers an unexpected exception with the 500 envelope, within the stack."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_tracking(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking)
        except Exception as exc:
            # Half a response cannot be replaced by another one; the server
            # closes the connection, which is the only honest answer left.
            if response_started:
                raise
            response = unhandled_error_response(exc, self.settings)
            await response(scope, receive, send)
