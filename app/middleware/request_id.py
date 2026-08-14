"""Correlation id assignment.

Mount this outermost. Every log line, every error envelope and the response
header all read the same id from here, which is what makes a single request
traceable end to end.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from uuid import uuid4

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"

#: Upper bound for an inbound correlation id we are willing to echo back.
MAX_REQUEST_ID_LENGTH = 128

# Correlation ids are echoed into response headers and log lines, so only a
# conservative, header-safe alphabet is accepted: alphanumerics plus the
# separators used by UUIDs, ULIDs and W3C trace ids. Anything else (control
# characters, CR/LF, spaces, unicode) is discarded and replaced with a freshly
# generated id rather than reflected back to the caller.
_SAFE_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def is_safe_request_id(value: object, max_length: int = MAX_REQUEST_ID_LENGTH) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= max_length
        and _SAFE_REQUEST_ID_PATTERN.match(value) is not None
    )


def resolve_request_id(
    header_value: str | None,
    max_length: int = MAX_REQUEST_ID_LENGTH,
) -> str:
    """Normalises an inbound header into a usable id, generating one if needed."""
    candidate = header_value.strip() if isinstance(header_value, str) else None
    if is_safe_request_id(candidate, max_length) and candidate is not None:
        return candidate
    return str(uuid4())


def get_request_id() -> str | None:
    """Correlation id of the request being handled, if any."""
    return _request_id.get()


class RequestIdMiddleware:
    """Assigns a correlation id and echoes it back on the response.

    Written as raw ASGI rather than on top of ``BaseHTTPMiddleware`` so the id is
    established before any other layer runs and stays available to the exception
    handlers, which is precisely where it is needed most.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        header: str = REQUEST_ID_HEADER,
        max_length: int = MAX_REQUEST_ID_LENGTH,
        trust_inbound_header: bool = True,
    ) -> None:
        self.app = app
        self.header = header.lower()
        self.max_length = max_length
        self.trust_inbound_header = trust_inbound_header

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        inbound = Headers(scope=scope).get(self.header) if self.trust_inbound_header else None
        request_id = resolve_request_id(inbound, self.max_length)
        token = _request_id.set(request_id)

        encoded = (self.header.encode("latin-1"), request_id.encode("latin-1"))

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append(encoded)
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _request_id.reset(token)
