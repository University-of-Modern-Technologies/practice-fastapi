"""Shared test fixtures.

The suite exercises the real application object through an in-process ASGI
transport: the same middleware stack, the same exception handlers, no socket.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field

from app.core.errors import ConflictError
from app.core.settings import Settings
from app.factory import create_app
from app.health.lifecycle import service_lifecycle

TEST_SECRET = "test-secret-value-that-is-long-enough"


@pytest.fixture
def settings() -> Settings:
    # `_env_file=None` keeps a developer's local `.env` out of the fixture: it
    # would otherwise supply values the tests never asked for — a configured
    # metrics token, say, which mounts a second scrape endpoint.
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql://user:pass@localhost:5432/practice_crm_test?schema=public",
        jwt_access_secret=TEST_SECRET,
        jwt_refresh_secret=TEST_SECRET,
        redis_url="redis://localhost:6379",
        mongodb_url="mongodb://localhost:27017/practice_events_test",
    )


class EchoPayload(BaseModel):
    email: str = Field(min_length=3)
    age: int = Field(ge=0)


def _create_probe_router() -> APIRouter:
    """Endpoints that exist only to drive the error and response machinery."""
    router = APIRouter()

    @router.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/conflict")
    async def conflict() -> None:
        raise ConflictError("Contact already exists", "CONTACT_EXISTS", {"field": "email"})

    @router.get("/unhandled")
    async def unhandled() -> None:
        message = "something went wrong internally"
        raise RuntimeError(message)

    @router.post("/echo")
    async def echo(payload: EchoPayload) -> dict[str, object]:
        return {"data": payload.model_dump()}

    return router


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    return create_app(settings, routers=[("/probe", _create_probe_router())])


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    # Server errors are converted to responses rather than re-raised, which is
    # what a real client would observe.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
