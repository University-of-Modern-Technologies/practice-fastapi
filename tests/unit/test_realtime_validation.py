"""Inbound frame validation and handshake token extraction."""

from __future__ import annotations

import json

import pytest

from app.realtime.auth import (
    ACCESS_TOKEN_SUBPROTOCOL_PREFIX,
    BEARER_SUBPROTOCOL,
    extract_access_token,
    select_subprotocol,
)
from app.realtime.schemas import (
    DecodedFrame,
    FrameRejected,
    ParsedFrame,
    PingMessage,
    SubscribeMessage,
    UnsubscribeMessage,
    decode_inbound_frame,
    parse_inbound_message,
    read_inbound_frame,
)


def test_subscribe_frame_is_accepted() -> None:
    result = read_inbound_frame(json.dumps({"type": "subscribe", "topic": "deals"}), 1024)

    assert isinstance(result, ParsedFrame)
    assert isinstance(result.message, SubscribeMessage)
    assert result.message.topic == "deals"


def test_unsubscribe_and_ping_frames_are_accepted() -> None:
    unsubscribe = parse_inbound_message('{"type":"unsubscribe","topic":"entity:order:o1"}')
    ping = parse_inbound_message('{"type":"ping"}')

    assert isinstance(unsubscribe, ParsedFrame)
    assert isinstance(unsubscribe.message, UnsubscribeMessage)
    assert isinstance(ping, ParsedFrame)
    assert isinstance(ping.message, PingMessage)


def test_oversized_frames_are_rejected_before_parsing() -> None:
    payload = json.dumps({"type": "subscribe", "topic": "deals", "pad": "x" * 100})

    result = read_inbound_frame(payload, 32)

    assert isinstance(result, FrameRejected)
    assert result.code == "MESSAGE_TOO_LARGE"


def test_size_limit_counts_bytes_not_characters() -> None:
    # Two-byte characters must not slip past a byte budget.
    assert isinstance(decode_inbound_frame("ää", 4), DecodedFrame)
    assert isinstance(decode_inbound_frame("äää", 4), FrameRejected)


def test_malformed_json_is_reported_as_invalid_message() -> None:
    result = parse_inbound_message("{not json")

    assert isinstance(result, FrameRejected)
    assert result.code == "INVALID_MESSAGE"


@pytest.mark.parametrize(
    "payload",
    [
        '{"type":"unknown"}',
        '{"topic":"deals"}',
        '{"type":"ping","extra":1}',
        '["subscribe","deals"]',
    ],
)
def test_structurally_wrong_frames_are_invalid_messages(payload: str) -> None:
    result = parse_inbound_message(payload)

    assert isinstance(result, FrameRejected)
    assert result.code == "INVALID_MESSAGE"


@pytest.mark.parametrize(
    "topic",
    ["contacts", "entity:invoice:1", "entity:deal:bad id", ""],
)
def test_unknown_topics_get_their_own_error_code(topic: str) -> None:
    result = parse_inbound_message(json.dumps({"type": "subscribe", "topic": topic}))

    assert isinstance(result, FrameRejected)
    assert result.code == "UNKNOWN_TOPIC"


def test_a_missing_topic_is_also_a_topic_problem() -> None:
    # Anything the validator blames on the `topic` field is reported as a topic
    # error, so the client is pointed at the field that is actually wrong.
    result = parse_inbound_message('{"type":"subscribe"}')

    assert isinstance(result, FrameRejected)
    assert result.code == "UNKNOWN_TOPIC"


def test_token_is_read_from_the_paired_subprotocol_form() -> None:
    headers = {"sec-websocket-protocol": f"{BEARER_SUBPROTOCOL}, jwt-value"}

    assert extract_access_token(headers) == "jwt-value"
    assert select_subprotocol(headers) == BEARER_SUBPROTOCOL


def test_token_is_read_from_the_single_value_subprotocol_form() -> None:
    headers = {"sec-websocket-protocol": f"{ACCESS_TOKEN_SUBPROTOCOL_PREFIX}jwt-value"}

    assert extract_access_token(headers) == "jwt-value"
    # Nothing is echoed back: the offer never contained the marker.
    assert select_subprotocol(headers) is None


def test_authorization_header_is_honoured_for_native_clients() -> None:
    assert extract_access_token({"authorization": "Bearer jwt-value"}) == "jwt-value"


def test_query_string_is_never_a_token_source() -> None:
    # The extractor only ever sees headers, so a token in the URL cannot be
    # picked up even by accident.
    assert extract_access_token({"x-query-string": "access_token=jwt-value"}) is None
    assert extract_access_token({}) is None
    assert extract_access_token({"sec-websocket-protocol": BEARER_SUBPROTOCOL}) is None
