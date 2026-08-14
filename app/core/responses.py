"""Response envelopes.

Three shapes cover every response the API produces:

* a single resource      ``{"data": {...}}``
* a page of resources    ``{"items": [...], "page": 1, "pageSize": 20, "total": 0}``
* a failure              ``{"error": {"code", "message", "details"}, "requestId": "..."}``

Keeping them here means a handler never hand-rolls the outer object, and the
client can rely on the shape without reading per-endpoint documentation.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.serializers import to_camel


class CamelModel(BaseModel):
    """Base for every schema that crosses the HTTP boundary.

    The wire vocabulary is camelCase while the Python vocabulary stays
    snake_case; declaring that once here keeps the two from drifting apart
    schema by schema.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class Envelope[T](BaseModel):
    """Wrapper for a single resource."""

    data: T


class Page[T](BaseModel):
    """Wrapper for a slice of a collection."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    items: Sequence[T]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)


class ErrorBody(BaseModel):
    """Machine-readable description of a single failure."""

    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    """Body returned for every non-2xx response produced by this application."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    error: ErrorBody
    request_id: str | None = None


def envelope[T](data: T) -> dict[str, Any]:
    """Wraps a single resource without going through a response model."""
    return {"data": data}


def page[T](items: Sequence[T], *, total: int, page_number: int, page_size: int) -> dict[str, Any]:
    """Wraps a slice of a collection without going through a response model."""
    return {"items": items, "page": page_number, "pageSize": page_size, "total": total}
