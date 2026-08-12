"""Structural types of the realtime channel.

Nothing here imports a transport or an authentication module. The gateway talks
to sockets through :class:`RealtimeSocketLike` and to identities through
:class:`AuthContextLike`, which is what keeps its core unit testable with plain
fakes and free of a dependency on the auth and RBAC modules.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol, runtime_checkable

#: Close code sent to every client during a graceful shutdown.
CLOSE_CODE_GOING_AWAY: Final = 1001

#: Close code used when the handshake carries no usable access token.
CLOSE_CODE_UNAUTHORIZED: Final = 1008

RealtimeErrorCode = Literal[
    "INVALID_MESSAGE",
    "MESSAGE_TOO_LARGE",
    "UNKNOWN_TOPIC",
    "TOPIC_FORBIDDEN",
    "SUBSCRIPTION_LIMIT_REACHED",
    "NOT_SUBSCRIBED",
    "INTERNAL_ERROR",
]

ERROR_INVALID_MESSAGE: Final[RealtimeErrorCode] = "INVALID_MESSAGE"
ERROR_MESSAGE_TOO_LARGE: Final[RealtimeErrorCode] = "MESSAGE_TOO_LARGE"
ERROR_UNKNOWN_TOPIC: Final[RealtimeErrorCode] = "UNKNOWN_TOPIC"
ERROR_TOPIC_FORBIDDEN: Final[RealtimeErrorCode] = "TOPIC_FORBIDDEN"
ERROR_SUBSCRIPTION_LIMIT: Final[RealtimeErrorCode] = "SUBSCRIPTION_LIMIT_REACHED"
ERROR_NOT_SUBSCRIBED: Final[RealtimeErrorCode] = "NOT_SUBSCRIBED"
ERROR_INTERNAL: Final[RealtimeErrorCode] = "INTERNAL_ERROR"

OutboundFrameType = Literal["connected", "subscribed", "unsubscribed", "event", "pong", "error"]

#: Outbound frames are JSON objects; the concrete shape depends on ``type``.
OutboundFrame = dict[str, Any]


@runtime_checkable
class AuthContextLike(Protocol):
    """Narrow view of an authenticated identity.

    Deliberately structural: the auth module owns the real context object, and
    the gateway only ever needs to label a connection and its logs.
    """

    @property
    def user_id(self) -> uuid.UUID: ...

    @property
    def session_id(self) -> uuid.UUID: ...


class RealtimeSocketLike(Protocol):
    """Minimal structural view of a client socket."""

    async def send_text(self, data: str) -> None: ...

    async def close(self, code: int = 1000, reason: str = "") -> None: ...


#: Verifies an access token and resolves the identity it represents. Injected by
#: the composition root; raising means the token is rejected.
VerifyAccessToken = Callable[[str], Awaitable[AuthContextLike]]

#: Authorisation hook: may this identity subscribe to this topic? Injected so
#: the gateway never imports RBAC while still enforcing the same permissions.
CanSubscribe = Callable[[AuthContextLike, str], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class RealtimeGatewayOptions:
    """Tunables of a gateway instance."""

    #: Hard cap on a single inbound frame. Larger frames are rejected.
    max_inbound_message_bytes: int = 8 * 1024
    #: Hard cap on concurrent subscriptions held by one connection.
    max_subscriptions_per_connection: int = 20


@dataclass(frozen=True, slots=True)
class RealtimeGatewayStats:
    """Current registry sizes; useful for health output and assertions."""

    connections: int
    topics: int
    subscriptions: int


@dataclass(slots=True)
class RealtimeConnection:
    """One authenticated socket and the topics it follows."""

    id: str
    socket: RealtimeSocketLike
    auth: AuthContextLike
    topics: set[str] = field(default_factory=set)
    is_open: bool = True


def connected_frame(connection_id: str, user_id: str) -> OutboundFrame:
    return {"type": "connected", "connectionId": connection_id, "userId": user_id}


def subscribed_frame(topic: str) -> OutboundFrame:
    return {"type": "subscribed", "topic": topic}


def unsubscribed_frame(topic: str) -> OutboundFrame:
    return {"type": "unsubscribed", "topic": topic}


def event_frame(topic: str, payload: Any) -> OutboundFrame:
    return {"type": "event", "topic": topic, "payload": payload}


def pong_frame() -> OutboundFrame:
    return {"type": "pong"}


def error_frame(code: RealtimeErrorCode, message: str) -> OutboundFrame:
    return {"type": "error", "code": code, "message": message}
