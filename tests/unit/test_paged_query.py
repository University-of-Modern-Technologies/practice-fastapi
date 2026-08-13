"""``PagedQuery``: the offset arithmetic and the shape of a page.

The model here is private to this file — a real mapped model would pull in
``app.db.base.Base`` and its shared metadata, which ``test_models.py`` audits
table-by-table. A throwaway model on its own declarative base keeps this test
from becoming a fixture every other model has to account for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import ColumnElement, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.paged_query import PagedQuery


class _Base(DeclarativeBase):
    pass


class Widget(_Base):
    __tablename__ = "paged_query_test_widgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)


@dataclass(frozen=True, slots=True)
class WidgetOut:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class WidgetParams:
    page: int
    page_size: int


class FakeScalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return list(self._values)

    def unique(self) -> FakeScalars:
        return self


class FakeResult:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._values)


class FakeSession:
    """Scripted stand-in: records every statement, answers from a queue."""

    def __init__(self, total: int | None, rows: list[Any]) -> None:
        self.scalar_queue: list[Any] = [total]
        self.execute_queue: list[list[Any]] = [rows]
        self.statements: list[Any] = []

    async def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        return self.scalar_queue.pop(0) if self.scalar_queue else None

    async def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.execute_queue.pop(0) if self.execute_queue else [])


class _WidgetPage(PagedQuery[Widget, WidgetParams, WidgetOut]):
    """A page with no filters of its own: only the template's arithmetic is
    under test here, not any particular resource's rules."""

    def _model(self) -> type[Widget]:
        return Widget

    def _build_filters(self, _params: WidgetParams) -> list[ColumnElement[bool]]:
        return []

    def _order_by(self, _params: WidgetParams) -> tuple[ColumnElement[Any], ...]:
        return (Widget.id.asc(),)

    def _to_dto(self, row: Widget) -> WidgetOut:
        return WidgetOut(id=row.id, name=row.name)


def make_page(session: FakeSession) -> _WidgetPage:
    return _WidgetPage(cast("AsyncSession", session))


async def test_the_first_page_starts_at_a_zero_offset() -> None:
    session = FakeSession(total=0, rows=[])

    await make_page(session).run(WidgetParams(page=1, page_size=20))

    _, select_statement = session.statements
    offset = select_statement._offset_clause
    assert offset is None or offset.value == 0


async def test_the_third_page_offsets_by_two_full_pages() -> None:
    session = FakeSession(total=0, rows=[])

    await make_page(session).run(WidgetParams(page=3, page_size=20))

    _, select_statement = session.statements
    assert select_statement._offset_clause.value == 40


async def test_the_limit_matches_the_requested_page_size() -> None:
    session = FakeSession(total=0, rows=[])

    await make_page(session).run(WidgetParams(page=1, page_size=7))

    _, select_statement = session.statements
    assert select_statement._limit_clause.value == 7


async def test_a_page_reports_the_total_alongside_its_rendered_slice() -> None:
    session = FakeSession(total=5, rows=[Widget(id=1, name="a"), Widget(id=2, name="b")])

    items, total = await make_page(session).run(WidgetParams(page=1, page_size=20))

    assert total == 5
    assert items == [WidgetOut(id=1, name="a"), WidgetOut(id=2, name="b")]


async def test_a_missing_total_is_reported_as_zero_rather_than_none() -> None:
    session = FakeSession(total=None, rows=[])

    _, total = await make_page(session).run(WidgetParams(page=1, page_size=20))

    assert total == 0


async def test_the_count_is_read_before_the_page_is_fetched() -> None:
    """Counting after paging would describe a set the page never saw."""
    session = FakeSession(total=0, rows=[])

    await make_page(session).run(WidgetParams(page=1, page_size=20))

    count_statement, select_statement = session.statements
    assert "count" in str(count_statement).lower()
    assert "count" not in str(select_statement).lower()
