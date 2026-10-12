"""The body guard answers 413 however an oversized body arrives."""

from __future__ import annotations

from collections.abc import AsyncIterator

from httpx import AsyncClient

CHUNK = b"x" * 65_536


async def _chunked_body(size: int) -> AsyncIterator[bytes]:
    """A body with no declared length, sent in pieces the way chunked uploads are."""
    yield b'{"email": "user@example.com", "age": 30, "padding": "'
    sent = 0
    while sent < size:
        yield CHUNK
        sent += len(CHUNK)
    yield b'"}'


async def test_a_chunked_body_over_the_limit_is_413_not_400(client: AsyncClient) -> None:
    response = await client.post(
        "/probe/echo",
        content=_chunked_body(2_000_000),
        headers={"content-type": "application/json"},
    )

    assert "content-length" not in response.request.headers
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


async def test_a_chunked_body_within_the_limit_still_reaches_the_route(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/probe/echo",
        content=_chunked_body(1),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["email"] == "user@example.com"
