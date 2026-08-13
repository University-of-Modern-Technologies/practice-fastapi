"""Gateway behaviour, driven through fake sockets and one live handshake."""

from __future__ import annotations

import json
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from starlette.types import Message

from app.core.settings import Settings
from app.factory import create_app
from app.realtime.auth import BEARER_SUBPROTOCOL
from app.realtime.gateway import RealtimeGateway, create_realtime_router
from app.realtime.types import (
    AuthContextLike,
    RealtimeGatewayOptions,
)

WS_PATH = "/api/v1/realtime"


DEFAULT_USER_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
DEFAULT_SESSION_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
OTHER_USER_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


@dataclass(frozen=True, slots=True)
class FakeAuth:
    """Structural stand-in for the auth module's context."""

    user_id: uuid.UUID = DEFAULT_USER_ID
    session_id: uuid.UUID = DEFAULT_SESSION_ID


@dataclass(slots=True)
class FakeSocket:
    """Records what the gateway wrote instead of opening a socket."""

    sent: list[dict[str, Any]] = field(default_factory=list)
    closed: tuple[int, str] | None = None
    fail_on_send: bool = False

    async def send_text(self, data: str) -> None:
        if self.fail_on_send:
            message = "socket is gone"
            raise RuntimeError(message)
        self.sent.append(json.loads(data))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)


async def _verify_ok(token: str) -> AuthContextLike:
    # A deterministic identity per token, so an assertion can name the caller.
    return FakeAuth(user_id=uuid.uuid5(uuid.NAMESPACE_OID, token))


async def _verify_fail(_token: str) -> AuthContextLike:
    message = "invalid token"
    raise ValueError(message)


async def _allow_all(_auth: AuthContextLike, _topic: str) -> bool:
    return True


async def _deny_all(_auth: AuthContextLike, _topic: str) -> bool:
    return False


def _gateway(
    *,
    can_subscribe: Any = _allow_all,
    options: RealtimeGatewayOptions | None = None,
) -> RealtimeGateway:
    return RealtimeGateway(
        ws_path=WS_PATH,
        verify_access_token=_verify_ok,
        can_subscribe=can_subscribe,
        options=options,
    )


async def test_registration_greets_the_client() -> None:
    gateway = _gateway()
    socket = FakeSocket()

    connection = await gateway.register(socket, FakeAuth())

    assert socket.sent == [
        {"type": "connected", "connectionId": connection.id, "userId": str(DEFAULT_USER_ID)}
    ]
    assert gateway.stats().connections == 1


async def test_subscribe_registers_on_both_sides() -> None:
    gateway = _gateway()
    socket = FakeSocket()
    connection = await gateway.register(socket, FakeAuth())

    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"deals"}')

    assert socket.sent[-1] == {"type": "subscribed", "topic": "deals"}
    assert gateway.stats() == type(gateway.stats())(connections=1, topics=1, subscriptions=1)
    assert connection.topics == {"deals"}


async def test_subscribe_is_idempotent() -> None:
    gateway = _gateway()
    connection = await gateway.register(FakeSocket(), FakeAuth())

    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"deals"}')
    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"deals"}')

    assert gateway.stats().subscriptions == 1


async def test_denied_subscription_never_reaches_the_registry() -> None:
    gateway = _gateway(can_subscribe=_deny_all)
    socket = FakeSocket()
    connection = await gateway.register(socket, FakeAuth())

    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"deals"}')

    assert socket.sent[-1]["type"] == "error"
    assert socket.sent[-1]["code"] == "TOPIC_FORBIDDEN"
    assert gateway.stats().subscriptions == 0


async def test_gateway_without_an_authoriser_denies_everything() -> None:
    gateway = RealtimeGateway(ws_path=WS_PATH, verify_access_token=_verify_ok)
    socket = FakeSocket()
    connection = await gateway.register(socket, FakeAuth())

    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"deals"}')

    assert socket.sent[-1]["code"] == "TOPIC_FORBIDDEN"


async def test_authoriser_failure_is_reported_as_internal_error() -> None:
    async def explode(_auth: AuthContextLike, _topic: str) -> bool:
        message = "rbac is down"
        raise RuntimeError(message)

    gateway = _gateway(can_subscribe=explode)
    socket = FakeSocket()
    connection = await gateway.register(socket, FakeAuth())

    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"deals"}')

    assert socket.sent[-1]["code"] == "INTERNAL_ERROR"
    assert gateway.stats().subscriptions == 0


async def test_unknown_topic_is_answered_not_disconnected() -> None:
    gateway = _gateway()
    socket = FakeSocket()
    connection = await gateway.register(socket, FakeAuth())

    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"contacts"}')

    assert socket.sent[-1]["code"] == "UNKNOWN_TOPIC"
    assert socket.closed is None
    assert gateway.stats().topics == 0


async def test_subscription_limit_is_enforced_with_an_error_frame() -> None:
    gateway = _gateway(options=RealtimeGatewayOptions(max_subscriptions_per_connection=2))
    socket = FakeSocket()
    connection = await gateway.register(socket, FakeAuth())

    for index in range(3):
        await gateway.handle_frame(
            connection, json.dumps({"type": "subscribe", "topic": f"entity:deal:d{index}"})
        )

    assert socket.sent[-1]["code"] == "SUBSCRIPTION_LIMIT_REACHED"
    assert socket.closed is None
    assert gateway.stats().subscriptions == 2


async def test_oversized_frame_is_answered_with_an_error_frame() -> None:
    gateway = _gateway(options=RealtimeGatewayOptions(max_inbound_message_bytes=16))
    socket = FakeSocket()
    connection = await gateway.register(socket, FakeAuth())

    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"entity:deal:d1"}')

    assert socket.sent[-1]["code"] == "MESSAGE_TOO_LARGE"
    assert socket.closed is None


async def test_unsubscribe_clears_both_sides_of_the_registry() -> None:
    gateway = _gateway()
    socket = FakeSocket()
    connection = await gateway.register(socket, FakeAuth())
    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"deals"}')

    await gateway.handle_frame(connection, '{"type":"unsubscribe","topic":"deals"}')

    assert socket.sent[-1] == {"type": "unsubscribed", "topic": "deals"}
    assert gateway.stats().topics == 0
    assert connection.topics == set()


async def test_unsubscribe_without_a_subscription_is_reported() -> None:
    gateway = _gateway()
    socket = FakeSocket()
    connection = await gateway.register(socket, FakeAuth())

    await gateway.handle_frame(connection, '{"type":"unsubscribe","topic":"deals"}')

    assert socket.sent[-1]["code"] == "NOT_SUBSCRIBED"


async def test_ping_is_answered_with_pong() -> None:
    gateway = _gateway()
    socket = FakeSocket()
    connection = await gateway.register(socket, FakeAuth())

    await gateway.handle_frame(connection, '{"type":"ping"}')

    assert socket.sent[-1] == {"type": "pong"}


async def test_publish_reaches_only_subscribers() -> None:
    gateway = _gateway()
    subscriber_socket = FakeSocket()
    bystander_socket = FakeSocket()
    subscriber = await gateway.register(subscriber_socket, FakeAuth())
    await gateway.register(bystander_socket, FakeAuth(user_id=OTHER_USER_ID))
    await gateway.handle_frame(subscriber, '{"type":"subscribe","topic":"deals"}')

    await gateway.publish("deals", {"id": "d1"})

    assert subscriber_socket.sent[-1] == {
        "type": "event",
        "topic": "deals",
        "payload": {"id": "d1"},
    }
    assert all(frame["type"] != "event" for frame in bystander_socket.sent)


async def test_publish_to_an_unknown_topic_is_a_no_op() -> None:
    gateway = _gateway()
    socket = FakeSocket()
    connection = await gateway.register(socket, FakeAuth())
    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"deals"}')
    before = len(socket.sent)

    await gateway.publish("contacts", {"id": "c1"})

    assert len(socket.sent) == before


async def test_a_broken_socket_does_not_break_the_fan_out() -> None:
    gateway = _gateway()
    broken = FakeSocket()
    healthy = FakeSocket()
    broken_connection = await gateway.register(broken, FakeAuth())
    healthy_connection = await gateway.register(healthy, FakeAuth(user_id=OTHER_USER_ID))
    await gateway.handle_frame(broken_connection, '{"type":"subscribe","topic":"deals"}')
    await gateway.handle_frame(healthy_connection, '{"type":"subscribe","topic":"deals"}')
    broken.fail_on_send = True

    await gateway.publish("deals", {"id": "d1"})

    assert healthy.sent[-1]["type"] == "event"


async def test_dropping_a_connection_frees_its_topics() -> None:
    gateway = _gateway()
    connection = await gateway.register(FakeSocket(), FakeAuth())
    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"deals"}')

    gateway.forget(connection)

    assert gateway.stats().connections == 0
    assert gateway.stats().topics == 0


async def test_the_gateway_never_evicts_a_silent_subscriber() -> None:
    """A passive listener is a healthy client, not a dead one.

    Liveness belongs to the transport, which pings on its own interval; nothing
    in the application may close a socket just because it stayed quiet.
    """
    gateway = _gateway()
    socket = FakeSocket()
    connection = await gateway.register(socket, FakeAuth())
    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"deals"}')

    assert not hasattr(gateway, "run_heartbeat_tick")
    assert socket.closed is None
    assert gateway.stats().connections == 1
    assert gateway.stats().subscriptions == 1


async def test_a_failed_write_leaves_the_connection_registered() -> None:
    """One bad write is not proof the peer is gone."""
    gateway = _gateway()
    socket = FakeSocket()
    connection = await gateway.register(socket, FakeAuth())
    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"deals"}')
    socket.fail_on_send = True

    await gateway.publish("deals", {"id": "d1"})

    assert gateway.stats().connections == 1
    assert gateway.stats().subscriptions == 1

    socket.fail_on_send = False
    await gateway.publish("deals", {"id": "d2"})

    assert socket.sent[-1]["payload"] == {"id": "d2"}


async def test_close_sends_going_away_to_every_socket() -> None:
    gateway = _gateway()
    first = FakeSocket()
    second = FakeSocket()
    connection = await gateway.register(first, FakeAuth())
    await gateway.register(second, FakeAuth(user_id=OTHER_USER_ID))
    await gateway.handle_frame(connection, '{"type":"subscribe","topic":"deals"}')

    await gateway.close()

    assert first.closed == (1001, "Server shutting down")
    assert second.closed == (1001, "Server shutting down")
    assert gateway.stats() == type(gateway.stats())(connections=0, topics=0, subscriptions=0)


class _WebSocketDriver:
    """Plays the ASGI server side of a handshake, without opening a socket."""

    def __init__(self, inbound: list[Message]) -> None:
        self._inbound = deque(inbound)
        self.sent: list[Message] = []

    async def receive(self) -> Message:
        if self._inbound:
            return self._inbound.popleft()
        return {"type": "websocket.disconnect", "code": 1000}

    async def send(self, message: Message) -> None:
        self.sent.append(message)

    def frames(self) -> list[dict[str, Any]]:
        return [
            json.loads(message["text"])
            for message in self.sent
            if message["type"] == "websocket.send"
        ]


async def _handshake(
    app: FastAPI, *, subprotocol_header: str | None, inbound: list[Message] | None = None
) -> _WebSocketDriver:
    headers: list[tuple[bytes, bytes]] = []
    if subprotocol_header is not None:
        headers.append((b"sec-websocket-protocol", subprotocol_header.encode()))

    scope: dict[str, Any] = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": WS_PATH,
        "raw_path": WS_PATH.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "subprotocols": [],
    }
    driver = _WebSocketDriver([{"type": "websocket.connect"}, *(inbound or [])])
    await app(scope, driver.receive, driver.send)
    return driver


def _build_app(settings: Settings, gateway: RealtimeGateway) -> FastAPI:
    return create_app(settings, routers=[("", create_realtime_router(gateway))])


async def test_handshake_reads_the_token_from_the_subprotocol(settings: Settings) -> None:
    app = _build_app(settings, _gateway())

    driver = await _handshake(
        app,
        subprotocol_header=f"{BEARER_SUBPROTOCOL}, jwt-value",
        inbound=[{"type": "websocket.receive", "text": '{"type":"subscribe","topic":"deals"}'}],
    )

    # Only the marker is echoed; the token never appears in a response header.
    assert driver.sent[0]["type"] == "websocket.accept"
    assert driver.sent[0]["subprotocol"] == BEARER_SUBPROTOCOL
    greeting, acknowledgement = driver.frames()
    assert greeting["type"] == "connected"
    # The identity comes from the injected verifier, which proves the
    # subprotocol value is what was verified.
    assert greeting["userId"] == str(uuid.uuid5(uuid.NAMESPACE_OID, "jwt-value"))
    assert acknowledgement == {"type": "subscribed", "topic": "deals"}


async def test_handshake_without_a_token_is_refused(settings: Settings) -> None:
    app = _build_app(settings, _gateway())

    driver = await _handshake(app, subprotocol_header=None)

    # Refusing before `websocket.accept` means the socket is never opened.
    assert driver.sent[0]["type"] == "websocket.close"
    assert driver.frames() == []


async def test_handshake_with_an_invalid_token_is_refused(settings: Settings) -> None:
    gateway = RealtimeGateway(
        ws_path=WS_PATH, verify_access_token=_verify_fail, can_subscribe=_allow_all
    )
    app = _build_app(settings, gateway)

    driver = await _handshake(app, subprotocol_header=f"{BEARER_SUBPROTOCOL}, jwt-value")

    assert driver.sent[0]["type"] == "websocket.close"
    assert driver.frames() == []
