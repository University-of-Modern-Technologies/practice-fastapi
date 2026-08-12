"""WebSocket gateway.

The gateway owns two things: a bidirectional registry of connections and the
topics they follow, and the inbound frame loop. Everything policy-shaped — how a
token becomes an identity, and whether an identity may follow a topic — is
injected, so this module imports neither the auth module nor RBAC while still
enforcing exactly the permissions they define.

Liveness is deliberately *not* tracked at the application level. The ASGI
WebSocket interface gives an application no way to emit a protocol-level ping,
and an application-level keepalive would evict a client that is merely quiet —
a passive subscriber that only listens is a perfectly healthy client. The
server's WebSocket implementation already pings every connection on its own
interval and tears down a peer that stops answering, which is exactly the
liveness check needed and the one browsers answer automatically.

The registry is deliberately two-sided: each connection holds its own topic set
and each topic holds its subscriber set. Unsubscribing and dropping a dead
connection therefore cost O(number of topics that connection follows) instead of
a scan over every subscriber in the process.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.realtime.auth import extract_access_token, select_subprotocol
from app.realtime.schemas import (
    FrameRejected,
    PingMessage,
    SubscribeMessage,
    read_inbound_frame,
)
from app.realtime.topics import parse_realtime_topic
from app.realtime.types import (
    CLOSE_CODE_GOING_AWAY,
    CLOSE_CODE_UNAUTHORIZED,
    ERROR_INTERNAL,
    ERROR_NOT_SUBSCRIBED,
    ERROR_SUBSCRIPTION_LIMIT,
    ERROR_TOPIC_FORBIDDEN,
    AuthContextLike,
    CanSubscribe,
    OutboundFrame,
    RealtimeConnection,
    RealtimeErrorCode,
    RealtimeGatewayOptions,
    RealtimeGatewayStats,
    RealtimeSocketLike,
    VerifyAccessToken,
    connected_frame,
    error_frame,
    event_frame,
    pong_frame,
    subscribed_frame,
    unsubscribed_frame,
)

logger = get_logger("realtime")


async def _deny_all(_auth: AuthContextLike, _topic: str) -> bool:
    """Secure default: without an injected authoriser nothing is subscribable."""
    return False


class RealtimeGateway:
    """Fan-out hub for authenticated WebSocket clients."""

    def __init__(
        self,
        *,
        ws_path: str,
        verify_access_token: VerifyAccessToken,
        can_subscribe: CanSubscribe | None = None,
        options: RealtimeGatewayOptions | None = None,
    ) -> None:
        self.ws_path = ws_path
        self._verify_access_token = verify_access_token
        if can_subscribe is None:
            logger.warning("No can_subscribe callback injected; every subscription is denied")
        self._can_subscribe: CanSubscribe = can_subscribe or _deny_all
        self._options = options or RealtimeGatewayOptions()

        self._connections: dict[str, RealtimeConnection] = {}
        self._topic_index: dict[str, set[str]] = {}
        self._closing = False

    # ------------------------------------------------------------------
    # registry
    # ------------------------------------------------------------------

    @property
    def options(self) -> RealtimeGatewayOptions:
        return self._options

    def stats(self) -> RealtimeGatewayStats:
        return RealtimeGatewayStats(
            connections=len(self._connections),
            topics=len(self._topic_index),
            subscriptions=sum(len(item.topics) for item in self._connections.values()),
        )

    async def _send(self, connection: RealtimeConnection, frame: OutboundFrame) -> None:
        if not connection.is_open:
            return
        try:
            await connection.socket.send_text(json.dumps(frame))
        # A broken socket must not break the fan-out to everyone else. The
        # connection is left in the registry: a single failed write is not proof
        # the peer is gone, and the transport reports a genuinely dead socket by
        # ending the receive loop, which is what removes it.
        except Exception:
            logger.warning("Failed to write realtime frame", connectionId=connection.id)

    async def _send_error(
        self, connection: RealtimeConnection, code: RealtimeErrorCode, message: str
    ) -> None:
        await self._send(connection, error_frame(code, message))

    def _unsubscribe_all(self, connection: RealtimeConnection) -> None:
        for topic in connection.topics:
            subscribers = self._topic_index.get(topic)
            if subscribers is None:
                continue
            subscribers.discard(connection.id)
            if not subscribers:
                del self._topic_index[topic]
        connection.topics.clear()

    def forget(self, connection: RealtimeConnection) -> None:
        """Removes a connection from both sides of the registry."""
        if self._connections.pop(connection.id, None) is None:
            return
        self._unsubscribe_all(connection)
        connection.is_open = False

    async def register(
        self, socket: RealtimeSocketLike, auth: AuthContextLike
    ) -> RealtimeConnection:
        """Registers an already authenticated socket and greets the client."""
        connection = RealtimeConnection(id=str(uuid4()), socket=socket, auth=auth)
        self._connections[connection.id] = connection

        logger.debug("Realtime client connected", connectionId=connection.id, userId=auth.user_id)
        await self._send(connection, connected_frame(connection.id, str(auth.user_id)))
        return connection

    # ------------------------------------------------------------------
    # inbound frames
    # ------------------------------------------------------------------

    async def _handle_subscribe(self, connection: RealtimeConnection, topic: str) -> None:
        if topic in connection.topics:
            await self._send(connection, subscribed_frame(topic))
            return

        limit = self._options.max_subscriptions_per_connection
        if len(connection.topics) >= limit:
            await self._send_error(
                connection,
                ERROR_SUBSCRIPTION_LIMIT,
                f"A connection may hold at most {limit} subscriptions",
            )
            return

        try:
            allowed = await self._can_subscribe(connection.auth, topic)
        except Exception:
            # An authoriser fault is not a client fault: report it as internal
            # rather than as a denial, which would look like a permission bug.
            logger.exception("Authorisation check failed", connectionId=connection.id, topic=topic)
            await self._send_error(
                connection, ERROR_INTERNAL, "Subscription could not be processed"
            )
            return

        if not allowed:
            logger.debug("Subscription denied", connectionId=connection.id, topic=topic)
            await self._send_error(connection, ERROR_TOPIC_FORBIDDEN, "Topic is not accessible")
            return

        # The connection may have been dropped while the async check ran.
        if connection.id not in self._connections:
            return

        connection.topics.add(topic)
        self._topic_index.setdefault(topic, set()).add(connection.id)
        await self._send(connection, subscribed_frame(topic))

    async def _handle_unsubscribe(self, connection: RealtimeConnection, topic: str) -> None:
        if topic not in connection.topics:
            await self._send_error(connection, ERROR_NOT_SUBSCRIBED, "Not subscribed to this topic")
            return

        connection.topics.discard(topic)
        subscribers = self._topic_index.get(topic)
        if subscribers is not None:
            subscribers.discard(connection.id)
            if not subscribers:
                del self._topic_index[topic]

        await self._send(connection, unsubscribed_frame(topic))

    async def handle_frame(self, connection: RealtimeConnection, data: str | bytes) -> None:
        """Validates and dispatches one inbound frame."""
        parsed = read_inbound_frame(data, self._options.max_inbound_message_bytes)
        if isinstance(parsed, FrameRejected):
            # Limits and malformed input answer with an error frame rather than a
            # disconnect: a buggy client should be told what is wrong, not dropped.
            await self._send_error(connection, parsed.code, parsed.reason)
            return

        message = parsed.message
        if isinstance(message, PingMessage):
            await self._send(connection, pong_frame())
            return

        if isinstance(message, SubscribeMessage):
            await self._handle_subscribe(connection, message.topic)
            return

        await self._handle_unsubscribe(connection, message.topic)

    # ------------------------------------------------------------------
    # fan-out and shutdown
    # ------------------------------------------------------------------

    async def publish(self, topic: str, event: Any) -> None:
        """Fans an event out to every authorised subscriber of ``topic``."""
        parsed = parse_realtime_topic(topic)
        if parsed is None:
            logger.warning("Refused to publish to an unknown realtime topic", topic=topic)
            return

        subscribers = self._topic_index.get(parsed.topic)
        if not subscribers:
            return

        frame = event_frame(parsed.topic, event)
        # Concurrent writes: one slow peer must not hold up the whole topic.
        targets = [
            connection
            for connection in (self._connections.get(item) for item in list(subscribers))
            if connection is not None
        ]
        await asyncio.gather(*(self._send(connection, frame) for connection in targets))

    async def close(self) -> None:
        """Closes every socket with code 1001 and empties the registry."""
        self._closing = True

        for connection in list(self._connections.values()):
            self._unsubscribe_all(connection)
            connection.is_open = False
            with contextlib.suppress(Exception):
                await connection.socket.close(CLOSE_CODE_GOING_AWAY, "Server shutting down")

        self._connections.clear()
        self._topic_index.clear()
        logger.info("Realtime gateway closed")

    # ------------------------------------------------------------------
    # transport binding
    # ------------------------------------------------------------------

    async def serve(self, websocket: WebSocket) -> None:
        """Drives one client socket for its whole lifetime.

        Authentication happens before the handshake is accepted, so an
        unauthenticated client never gets an open socket. The access token is
        read from ``Sec-WebSocket-Protocol`` (see :mod:`app.realtime.auth`) and
        never from the query string.
        """
        if self._closing:
            await websocket.close(CLOSE_CODE_GOING_AWAY, "Server shutting down")
            return

        token = extract_access_token(websocket.headers)
        if token is None:
            logger.debug("Rejected unauthenticated realtime handshake")
            await websocket.close(CLOSE_CODE_UNAUTHORIZED, "Missing access token")
            return

        try:
            auth = await self._verify_access_token(token)
        except Exception:
            # Any verification fault is a rejection; the reason never reaches
            # the client, so an attacker learns nothing from probing.
            logger.debug("Rejected realtime handshake with an invalid access token")
            await websocket.close(CLOSE_CODE_UNAUTHORIZED, "Invalid access token")
            return

        await websocket.accept(subprotocol=select_subprotocol(websocket.headers))
        connection = await self.register(websocket, auth)

        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break

                data = message.get("text")
                if data is None:
                    data = message.get("bytes")
                if data is None:
                    continue

                await self.handle_frame(connection, data)
        except WebSocketDisconnect:
            pass
        finally:
            self.forget(connection)


def create_realtime_router(gateway: RealtimeGateway) -> APIRouter:
    """Router exposing the gateway at ``settings.ws_path``."""
    router = APIRouter()

    @router.websocket(gateway.ws_path)
    async def realtime_endpoint(websocket: WebSocket) -> None:
        await gateway.serve(websocket)

    return router
