"""Query parameters shared by every collection endpoint.

Declared once so that ``page``, ``pageSize`` and the sort pair mean the same
thing — and enforce the same bounds — on all thirteen modules.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.serializers import to_camel

SortOrder = Literal["asc", "desc"]

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class ListQuery(BaseModel):
    """Pagination and free-text search accepted by list endpoints.

    Modules extend this with their own filters and their own ``sort_by``
    literal; the base deliberately carries no sort field because the set of
    sortable columns differs per resource.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    search: str | None = Field(default=None, min_length=1, max_length=64)
    sort_order: SortOrder = "desc"

    @property
    def offset(self) -> int:
        """Row offset the page starts at."""
        return (self.page - 1) * self.page_size
