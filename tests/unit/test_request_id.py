from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.middleware.request_id import (
    REQUEST_ID_HEADER,
    is_safe_request_id,
    resolve_request_id,
)


@pytest.mark.parametrize(
    "value",
    [
        "01J8Z5T3M0000000000000",
        "9f1c1b2e-0000-4000-8000-000000000000",
        "trace:abc-123.4",
    ],
)
def test_conservative_alphabet_is_accepted(value: str) -> None:
    assert is_safe_request_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "has space",
        "line\nbreak",
        "юнікод",
        "x" * 129,
    ],
)
def test_unsafe_values_are_rejected(value: str) -> None:
    assert not is_safe_request_id(value)


def test_unsafe_inbound_id_is_replaced_rather_than_echoed() -> None:
    resolved = resolve_request_id("bad\r\nvalue")

    assert resolved != "bad\r\nvalue"
    assert is_safe_request_id(resolved)


def test_missing_header_generates_an_id() -> None:
    assert is_safe_request_id(resolve_request_id(None))


async def test_safe_inbound_id_is_reused_on_the_response(client: AsyncClient) -> None:
    response = await client.get("/probe/ok", headers={REQUEST_ID_HEADER: "trace-42"})

    assert response.headers[REQUEST_ID_HEADER] == "trace-42"


async def test_every_response_carries_an_id(client: AsyncClient) -> None:
    response = await client.get("/probe/ok")

    assert is_safe_request_id(response.headers[REQUEST_ID_HEADER])
