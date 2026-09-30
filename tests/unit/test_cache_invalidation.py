"""A successful write drops the cached reports; a read or a failure does not."""

from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient

from app.modules.analytics.cache_keys import analytics_prefix


class RecordingCache:
    def __init__(self) -> None:
        self.dropped: list[str] = []

    async def invalidate_prefix(self, prefix: str) -> None:
        self.dropped.append(prefix)


def _install(app: FastAPI) -> RecordingCache:
    cache = RecordingCache()
    app.state.cache = cache
    return cache


async def test_a_successful_write_drops_the_reports(app: FastAPI, client: AsyncClient) -> None:
    cache = _install(app)

    response = await client.post("/probe/echo", json={"email": "a@b.c", "age": 1})

    assert response.status_code == 200
    assert cache.dropped == [analytics_prefix()]


async def test_a_read_keeps_the_reports(app: FastAPI, client: AsyncClient) -> None:
    cache = _install(app)

    await client.get("/probe/ok")

    assert cache.dropped == []


async def test_a_rejected_write_keeps_the_reports(app: FastAPI, client: AsyncClient) -> None:
    cache = _install(app)

    response = await client.post("/probe/echo", json={"email": "", "age": -1})

    assert response.status_code == 400
    assert cache.dropped == []


async def test_signing_in_keeps_the_reports(app: FastAPI, client: AsyncClient) -> None:
    cache = _install(app)

    await client.post("/api/v1/auth/login", json={})

    assert cache.dropped == []


async def test_without_a_cache_a_write_still_goes_through(client: AsyncClient) -> None:
    response = await client.post("/probe/echo", json={"email": "a@b.c", "age": 1})

    assert response.status_code == 200
