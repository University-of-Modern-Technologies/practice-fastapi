"""An unexpected failure still answers under the id of the request that caused it.

Starlette runs the last-resort handler outside every user middleware, after the
request id middleware has already unwound. These tests pin down that the 500
envelope, its header and its log line carry the same id every other response
does, rather than `null`.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter
from httpx import AsyncClient

from app.core import handlers
from app.core.settings import Settings
from app.factory import create_app
from app.health.lifecycle import service_lifecycle
from app.middleware.request_id import REQUEST_ID_HEADER, get_request_id, is_safe_request_id


class RecordingLogger:
    """Notes which correlation id was current whenever a line was emitted."""

    def __init__(self) -> None:
        self.request_ids: list[str | None] = []

    def error(self, _event: str, **_fields: Any) -> None:
        self.request_ids.append(get_request_id())

    def warning(self, _event: str, **_fields: Any) -> None:
        self.request_ids.append(get_request_id())


async def test_an_unhandled_error_carries_a_request_id_string(client: AsyncClient) -> None:
    response = await client.get("/probe/unhandled")

    assert response.status_code == 500
    request_id = response.json()["requestId"]
    assert isinstance(request_id, str)
    assert is_safe_request_id(request_id)
    assert response.headers[REQUEST_ID_HEADER] == request_id


async def test_an_unhandled_error_echoes_the_inbound_request_id(client: AsyncClient) -> None:
    response = await client.get("/probe/unhandled", headers={REQUEST_ID_HEADER: "trace-500"})

    assert response.status_code == 500
    assert response.json()["requestId"] == "trace-500"
    # Set once: the response never passes back through the middleware.
    assert response.headers.get_list(REQUEST_ID_HEADER) == ["trace-500"]


async def test_the_unhandled_error_is_logged_under_the_same_request_id(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = RecordingLogger()
    monkeypatch.setattr(handlers, "logger", recorder)

    response = await client.get("/probe/unhandled", headers={REQUEST_ID_HEADER: "trace-log"})

    assert response.status_code == 500
    assert recorder.request_ids == ["trace-log"]


async def test_the_handler_leaves_no_request_id_behind(client: AsyncClient) -> None:
    await client.get("/probe/unhandled", headers={REQUEST_ID_HEADER: "trace-leak"})

    assert get_request_id() is None


# The test client warns, on import, about the HTTP library it is built on; that
# is the client's own business and says nothing about the code under test.
@pytest.mark.filterwarnings("ignore:Using .httpx. with .starlette.testclient. is deprecated")
def test_a_raising_route_answers_with_its_request_id_through_test_client(
    settings: Settings,
) -> None:
    from fastapi.testclient import TestClient  # noqa: PLC0415

    router = APIRouter()

    @router.get("/boom")
    async def boom() -> None:
        message = "boom"
        raise LookupError(message)

    service_lifecycle.reset()
    service_lifecycle.mark_started()
    app = create_app(settings, routers=[("/probe", router)])

    # A real server hands every request a `state` mapping of its own; the test
    # client does the same, so the id is recorded where it is in production.
    test_client = TestClient(app, raise_server_exceptions=False)
    generated = test_client.get("/probe/boom")
    echoed = test_client.get("/probe/boom", headers={REQUEST_ID_HEADER: "trace-tc"})

    assert generated.status_code == 500
    assert generated.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert isinstance(generated.json()["requestId"], str)
    assert generated.json()["requestId"] == generated.headers[REQUEST_ID_HEADER]

    assert echoed.status_code == 500
    assert echoed.json()["requestId"] == "trace-tc"
    assert echoed.headers[REQUEST_ID_HEADER] == "trace-tc"
