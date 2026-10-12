"""A crash is answered like any other response.

Starlette sends the last-resort handler to its outermost layer, so a 500 built
there skipped the security headers and CORS: a browser got an unhardened
response, and a cross-origin caller could not read the envelope at all. The
sibling backend answers a crash through its whole middleware chain; these tests
pin down that this one does too.
"""

from __future__ import annotations

from httpx import AsyncClient

from app.middleware.request_id import REQUEST_ID_HEADER
from app.middleware.security_headers import BASE_HEADERS

ORIGIN = "http://localhost:3000"


async def test_a_crash_carries_the_cors_headers(client: AsyncClient) -> None:
    response = await client.get("/probe/unhandled", headers={"origin": ORIGIN})

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"


async def test_a_crash_carries_the_security_headers(client: AsyncClient) -> None:
    response = await client.get("/probe/unhandled")

    assert response.status_code == 500
    for name, value in BASE_HEADERS:
        assert response.headers.get(name) == value, name
    assert "content-security-policy" in response.headers


async def test_a_crash_carries_its_request_id_once(client: AsyncClient) -> None:
    response = await client.get("/probe/unhandled", headers={REQUEST_ID_HEADER: "trace-crash"})

    assert response.json()["requestId"] == "trace-crash"
    assert response.headers.get_list(REQUEST_ID_HEADER) == ["trace-crash"]


async def test_a_crash_and_a_refusal_share_the_same_header_set(client: AsyncClient) -> None:
    crash = await client.get("/probe/unhandled", headers={"origin": ORIGIN})
    refusal = await client.get("/probe/conflict", headers={"origin": ORIGIN})

    variable = {"content-length", REQUEST_ID_HEADER}
    assert set(crash.headers) - variable == set(refusal.headers) - variable
