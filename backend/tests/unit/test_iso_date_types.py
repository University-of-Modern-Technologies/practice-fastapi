"""Dates on input are spelled as dates, never as Unix timestamps.

Left to its defaults the validator reads ``1704067200`` — a number, or the same
digits in a string — as ``2024-01-01``. The sibling backend refuses it, so a
client that works against one backend would break against the other.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

import pytest
from fastapi import APIRouter, FastAPI, Query
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.core.settings import Settings
from app.core.validation import IsoDate, IsoDatetime
from app.factory import create_app
from app.health.lifecycle import service_lifecycle

TIMESTAMP = 1_704_067_200  # 2024-01-01T00:00:00Z

iso_date = TypeAdapter(IsoDate)
iso_datetime = TypeAdapter(IsoDatetime)


@pytest.mark.parametrize("value", [TIMESTAMP, float(TIMESTAMP), str(TIMESTAMP), True])
def test_a_date_refuses_a_timestamp(value: object) -> None:
    with pytest.raises(ValidationError):
        iso_date.validate_python(value)


@pytest.mark.parametrize("value", ["2024-01-01T00:00:00Z", "2024-1-1", "01.01.2024", ""])
def test_a_date_refuses_anything_but_yyyy_mm_dd(value: str) -> None:
    with pytest.raises(ValidationError):
        iso_date.validate_python(value)


def test_a_date_refuses_an_impossible_calendar_day() -> None:
    with pytest.raises(ValidationError):
        iso_date.validate_python("2024-02-30")


def test_a_date_accepts_yyyy_mm_dd_and_a_parsed_date() -> None:
    assert iso_date.validate_python("2024-01-01") == date(2024, 1, 1)
    assert iso_date.validate_json('"2024-01-01"') == date(2024, 1, 1)
    assert iso_date.validate_python(date(2024, 1, 1)) == date(2024, 1, 1)


def test_a_date_is_still_documented_as_a_date() -> None:
    assert iso_date.json_schema() == {"type": "string", "format": "date"}


@pytest.mark.parametrize("value", [TIMESTAMP, float(TIMESTAMP), str(TIMESTAMP), "-1"])
def test_a_datetime_refuses_a_timestamp(value: object) -> None:
    with pytest.raises(ValidationError):
        iso_datetime.validate_python(value)


def test_a_datetime_still_accepts_iso_8601() -> None:
    assert iso_datetime.validate_python("2024-01-01T00:00:00Z") == datetime(2024, 1, 1, tzinfo=UTC)


class _Body(BaseModel):
    due: IsoDate


class _Filters(BaseModel):
    due_from: IsoDate | None = None


async def test_a_timestamp_is_a_400_on_the_wire(settings: Settings) -> None:
    router = APIRouter()

    @router.post("/body")
    async def body(payload: _Body) -> dict[str, str]:
        return {"due": payload.due.isoformat()}

    # The way the modules declare their filters: one model, read from the query.
    @router.get("/query")
    async def query(filters: Annotated[_Filters, Query()]) -> dict[str, str | None]:
        due = filters.due_from
        return {"due": due.isoformat() if due else None}

    service_lifecycle.reset()
    service_lifecycle.mark_started()
    app: FastAPI = create_app(settings, routers=[("/probe", router)])
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        refused_body = await client.post("/probe/body", json={"due": TIMESTAMP})
        refused_query = await client.get("/probe/query", params={"due_from": str(TIMESTAMP)})
        accepted = await client.get("/probe/query", params={"due_from": "2024-01-01"})

    assert refused_body.status_code == 400
    assert refused_body.json()["error"]["details"]["fieldErrors"]["body"][0].startswith("due:")
    assert refused_query.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json() == {"due": "2024-01-01"}
