"""Inbound frame validation.

Nothing in this module raises: every failure comes back as a typed result, so a
malformed client frame turns into a structured ``error`` frame instead of an
exception unwinding the connection loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from app.realtime.topics import MAX_TOPIC_LENGTH, is_realtime_topic
from app.realtime.types import (
    ERROR_INVALID_MESSAGE,
    ERROR_MESSAGE_TOO_LARGE,
    ERROR_UNKNOWN_TOPIC,
    RealtimeErrorCode,
)


def _require_known_topic(value: str) -> str:
    if not is_realtime_topic(value):
        message = "Unknown topic"
        raise ValueError(message)
    return value


RealtimeTopicField = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_TOPIC_LENGTH),
    AfterValidator(_require_known_topic),
]


class _InboundBase(BaseModel):
    # Unknown keys are rejected rather than ignored: a client sending them is
    # speaking a protocol this server does not implement, and silently dropping
    # them would hide the mismatch until it mattered.
    model_config = ConfigDict(extra="forbid")


class SubscribeMessage(_InboundBase):
    type: Literal["subscribe"]
    topic: RealtimeTopicField


class UnsubscribeMessage(_InboundBase):
    type: Literal["unsubscribe"]
    topic: RealtimeTopicField


class PingMessage(_InboundBase):
    type: Literal["ping"]


InboundMessage = SubscribeMessage | UnsubscribeMessage | PingMessage

_INBOUND_ADAPTER: TypeAdapter[InboundMessage] = TypeAdapter(
    Annotated[InboundMessage, Field(discriminator="type")]
)


@dataclass(frozen=True, slots=True)
class DecodedFrame:
    """A frame that fits the size limit, decoded to text."""

    text: str


@dataclass(frozen=True, slots=True)
class FrameRejected:
    """Why a frame was refused, in the vocabulary the client sees."""

    code: RealtimeErrorCode
    reason: str


@dataclass(frozen=True, slots=True)
class ParsedFrame:
    """A validated inbound message."""

    message: InboundMessage


DecodeResult = DecodedFrame | FrameRejected
InboundParseResult = ParsedFrame | FrameRejected


def decode_inbound_frame(data: str | bytes, max_bytes: int) -> DecodeResult:
    """Decodes a frame to text, enforcing the inbound size limit first."""
    raw = data.encode("utf-8") if isinstance(data, str) else data

    if len(raw) > max_bytes:
        return FrameRejected(
            code=ERROR_MESSAGE_TOO_LARGE,
            reason=f"Message exceeds {max_bytes} bytes",
        )

    try:
        return DecodedFrame(text=raw.decode("utf-8"))
    except UnicodeDecodeError:
        return FrameRejected(code=ERROR_INVALID_MESSAGE, reason="Message is not valid UTF-8")


def _describe(error: PydanticValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        if item["loc"]
        else item["msg"]
        for item in error.errors()
    )


def parse_inbound_message(text: str) -> InboundParseResult:
    """Parses and validates a decoded frame body."""
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError):
        return FrameRejected(code=ERROR_INVALID_MESSAGE, reason="Message is not valid JSON")

    try:
        return ParsedFrame(message=_INBOUND_ADAPTER.validate_python(payload))
    except PydanticValidationError as error:
        # A bad topic gets its own code so the client can tell "you asked for
        # something that does not exist" from "your frame is malformed".
        mentions_topic = any("topic" in item["loc"] for item in error.errors())
        code = ERROR_UNKNOWN_TOPIC if mentions_topic else ERROR_INVALID_MESSAGE
        return FrameRejected(code=code, reason=_describe(error))


def read_inbound_frame(data: str | bytes, max_bytes: int) -> InboundParseResult:
    """Decodes and validates a raw transport frame in one step."""
    decoded = decode_inbound_frame(data, max_bytes)
    if isinstance(decoded, FrameRejected):
        return decoded
    return parse_inbound_message(decoded.text)
