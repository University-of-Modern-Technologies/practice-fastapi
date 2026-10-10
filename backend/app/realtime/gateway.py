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

A connection lives no longer than the credentials it was opened with. It is
closed with ``CLOSE_CODE_SESSION_ENDED`` when the access token presented at the
handshake expires, and as soon as the session behind it ends — the auth and
user services report that through ``sessions_revoked`` and
``user_sessions_revoked`` once the change has committed.

The registry is deliberately two-sided: each connection holds its own topic set
and each topic holds its subscriber set. Unsubscribing and dropping a dead
connection therefore cost O(number of topics that connection follows) instead of
a scan over every subscriber in the process.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from starlette.responses import Response
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.events.sanitize import sanitize_event_payload
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
    CLOSE_CODE_SESSION_ENDED,
    CLOSE_CODE_UNAUTHORIZED,
    CLOSE_REASON_SESSION_ENDED,
    CLOSE_REASON_TOKEN_EXPIRED,
    ERROR_INTERNAL,
    ERROR_NOT_SUBSCRIBED,
    ERROR_SUBSCRIPTION_LIMIT,
    ERROR_TOPIC_FORBIDDEN,
    HANDSHAKE_STATUS_UNAUTHORIZED,
    HANDSHAKE_STATUS_UNAVAILABLE,
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

#: ASGI extension that lets an application answer a handshake with plain HTTP.
_DENIAL_RESPONSE_EXTENSION = "websocket.http.response"


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
        # Closes started from synchronous code, held until they finish so the
        # event loop cannot collect them half-way.
        self._closing_sockets: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # registry
    # ------------------------------------------------------------------

    @property
    def options(self) -> RealtimeGatewayOptions:
        return self._options

    @property
    def is_closing(self) -> bool:
        """Whether shutdown has begun; read afresh after every ``await``."""
        return self._closing

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

    @staticmethod
    def _clear_expiry(connection: RealtimeConnection) -> None:
        if connection.expiry is not None:
            connection.expiry.cancel()
            connection.expiry = None

    def forget(self, connection: RealtimeConnection) -> None:
        """Removes a connection from both sides of the registry."""
        if self._connections.pop(connection.id, None) is None:
            return
        self._clear_expiry(connection)
        self._unsubscribe_all(connection)
        connection.is_open = False

    def _end_session(self, connection: RealtimeConnection, reason: str) -> None:
        """Closes a socket whose credentials are no longer valid.

        The connection leaves the registry first, so not one more event reaches
        it while the close handshake is under way. The receive loop that serves
        it then ends on the disconnect that follows.
        """
        if connection.id not in self._connections:
            return
        self.forget(connection)
        logger.debug("Closing realtime socket", connectionId=connection.id, reason=reason)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._close_socket(connection, reason))
        self._closing_sockets.add(task)
        task.add_done_callback(self._closing_sockets.discard)

    @staticmethod
    async def _close_socket(connection: RealtimeConnection, reason: str) -> None:
        try:
            await connection.socket.close(CLOSE_CODE_SESSION_ENDED, reason)
        except Exception:
            logger.warning("Socket close failed", connectionId=connection.id)

    def _arm_expiry(self, connection: RealtimeConnection) -> None:
        expires_at = connection.auth.expires_at
        if expires_at is None:
            return
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        deadline = expires_at

        def on_expiry() -> None:
            connection.expiry = None
            # The loop measures time on its own clock, the token on the wall
            # clock; a timer that fires ahead of the token is simply re-armed.
            if datetime.now(tz=UTC) < deadline:
                self._arm_expiry(connection)
                return
            self._end_session(connection, CLOSE_REASON_TOKEN_EXPIRED)

        remaining = (deadline - datetime.now(tz=UTC)).total_seconds()
        connection.expiry = asyncio.get_running_loop().call_later(max(remaining, 0.0), on_expiry)

    def _end_sessions_where(self, matches: Callable[[AuthContextLike], bool]) -> None:
        for connection in list(self._connections.values()):
            if matches(connection.auth):
                self._end_session(connection, CLOSE_REASON_SESSION_ENDED)

    def sessions_revoked(self, session_ids: Sequence[uuid.UUID]) -> None:
        """Closes every socket opened through one of these sessions.

        Called once the change that ended them has committed.
        """
        ended = {uuid.UUID(str(session_id)) for session_id in session_ids}
        if ended:
            self._end_sessions_where(lambda auth: auth.session_id in ended)

    def user_sessions_revoked(self, user_id: uuid.UUID) -> None:
        """The same, for every socket the user holds: all their sessions ended."""
        ended = uuid.UUID(str(user_id))
        self._end_sessions_where(lambda auth: auth.user_id == ended)

    async def register(
        self, socket: RealtimeSocketLike, auth: AuthContextLike
    ) -> RealtimeConnection:
        """Registers an already authenticated socket and greets the client."""
        connection = RealtimeConnection(id=str(uuid4()), socket=socket, auth=auth)
        self._connections[connection.id] = connection
        self._arm_expiry(connection)

        logger.debug("Realtime client connected", connectionId=connection.id, userId=auth.user_id)
        await self._send(connection, connected_frame(connection.id, str(auth.user_id)))
        return connection

    # ------------------------------------------------------------------
    # inbound frames
    # ------------------------------------------------------------------

    async def _settled_without_check(self, connection: RealtimeConnection, topic: str) -> bool:
        """Answers a subscribe that needs no authorisation check.

        That is one already held, or one over the limit. Returns whether it
        answered.
        """
        if topic in connection.topics:
            await self._send(connection, subscribed_frame(topic))
            return True

        limit = self._options.max_subscriptions_per_connection
        if len(connection.topics) >= limit:
            await self._send_error(
                connection,
                ERROR_SUBSCRIPTION_LIMIT,
                f"A connection may hold at most {limit} subscriptions",
            )
            return True

        return False

    async def _handle_subscribe(self, connection: RealtimeConnection, topic: str) -> None:
        if await self._settled_without_check(connection, topic):
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

        # The connection may have been dropped while the async check ran, and
        # the registry is read again rather than trusted from before the await.
        if connection.id not in self._connections:
            return
        if await self._settled_without_check(connection, topic):
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

        # The same redaction the event log applies on the way in: a secret that
        # slipped into a domain payload must not reach a browser either. It also
        # reduces the payload to plain JSON, so a UUID or a Decimal in it can no
        # longer make the write fail.
        frame = event_frame(parsed.topic, sanitize_event_payload(event))
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
            self._clear_expiry(connection)
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

    @staticmethod
    async def _refuse(websocket: WebSocket, status_code: int, close_code: int, reason: str) -> None:
        """Refuses a handshake before it is accepted.

        The answer is a plain HTTP status — 401 for a missing or rejected token,
        503 while shutting down — the same status the sibling deployment sends
        from its upgrade handler. Closing an unaccepted socket instead would
        make the ASGI server answer 403 for every reason alike. A server
        without the denial-response extension still gets the close.
        """
        if _DENIAL_RESPONSE_EXTENSION in websocket.scope.get("extensions", {}):
            await websocket.send_denial_response(Response(status_code=status_code))
            return
        await websocket.close(close_code, reason)

    async def serve(self, websocket: WebSocket) -> None:
        """Drives one client socket for its whole lifetime.

        Authentication happens before the handshake is accepted, so an
        unauthenticated client never gets an open socket. The access token is
        read from ``Sec-WebSocket-Protocol`` (see :mod:`app.realtime.auth`) and
        never from the query string.
        """
        if self._closing:
            await self._refuse(
                websocket,
                HANDSHAKE_STATUS_UNAVAILABLE,
                CLOSE_CODE_GOING_AWAY,
                "Server shutting down",
            )
            return

        token = extract_access_token(websocket.headers)
        if token is None:
            logger.debug("Rejected unauthenticated realtime handshake")
            await self._refuse(
                websocket,
                HANDSHAKE_STATUS_UNAUTHORIZED,
                CLOSE_CODE_UNAUTHORIZED,
                "Missing access token",
            )
            return

        try:
            auth = await self._verify_access_token(token)
        except Exception:
            # Any verification fault is a rejection; the reason never reaches
            # the client, so an attacker learns nothing from probing.
            logger.debug("Rejected realtime handshake with an invalid access token")
            await self._refuse(
                websocket,
                HANDSHAKE_STATUS_UNAUTHORIZED,
                CLOSE_CODE_UNAUTHORIZED,
                "Invalid access token",
            )
            return

        # Verification awaits the database, and shutdown may have begun in the
        # meantime: accepting now would register a socket that `close` has
        # already swept past, and that nothing would ever close.
        if self.is_closing:
            await self._refuse(
                websocket,
                HANDSHAKE_STATUS_UNAVAILABLE,
                CLOSE_CODE_GOING_AWAY,
                "Server shutting down",
            )
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
