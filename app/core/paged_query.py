"""The canonical shape of a filtered, sorted, paginated read.

Every ``list`` endpoint in this codebase needs the same four steps, in the
same order: turn the caller's filters into a ``WHERE`` clause, count how many
rows match it, fetch one page of those rows, and render each row for the wire.
Getting that order wrong — counting after paging, say, or paging an
unfiltered query — is an easy mistake to make by hand and a silent one to
miss in review.

Fixing the order here, once, and asking each resource only for the parts that
are actually specific to it — which table, which predicates, which order,
which DTO — is what rules that mistake out structurally rather than relying on
every author to get four repeated steps right every time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession


@runtime_checkable
class PageParams(Protocol):
    """What a page query needs from its parameters, whatever else they carry.

    Spelled as read-only properties rather than plain attributes: several
    params types are frozen, and a plain attribute in a ``Protocol`` demands a
    setter as well as a getter.
    """

    @property
    def page(self) -> int: ...

    @property
    def page_size(self) -> int: ...


class PagedQuery[ModelT, ParamsT: PageParams, OutT](ABC):
    """Runs one page of a query, delegating only what differs per resource.

    A fresh instance is built per call, holding whatever the resource needs
    beyond the query params themselves — an access grant, an actor id — so the
    abstract steps below can close over it instead of threading it through
    every method signature.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(self, params: ParamsT) -> tuple[list[OutT], int]:
        """One page of rows, plus the size of the whole filtered set."""
        criteria = self._build_filters(params)
        total = await self._session.scalar(
            select(func.count()).select_from(self._model()).where(*criteria)
        )
        result = await self._session.execute(
            select(self._model())
            .options(*self._load_options())
            .where(*criteria)
            .order_by(*self._order_by(params))
            .offset((params.page - 1) * params.page_size)
            .limit(params.page_size)
        )
        scalars = result.scalars()
        rows = scalars.unique().all() if self._distinct_rows() else scalars.all()
        return [self._to_dto(row) for row in rows], int(total or 0)

    @abstractmethod
    def _model(self) -> type[ModelT]:
        """The table the count and the page are both drawn from."""

    @abstractmethod
    def _build_filters(self, params: ParamsT) -> list[ColumnElement[bool]]:
        """Every predicate the page is narrowed by, including invisible ones
        such as a soft-delete guard or an access scope — not only the ones the
        caller's query parameters spelled out."""

    @abstractmethod
    def _order_by(self, params: ParamsT) -> Sequence[ColumnElement[Any]]:
        """The sort, including whatever column breaks ties between pages."""

    @abstractmethod
    def _to_dto(self, row: ModelT) -> OutT:
        """Renders one row in the shape the API publishes."""

    def _load_options(self) -> Sequence[Any]:
        """Eager-loading options for the page statement; none by default."""
        return ()

    def _distinct_rows(self) -> bool:
        """Whether eager-loaded collections require de-duplicating rows.

        Only a query that joins in a collection through ``_load_options``
        needs this — the join can otherwise repeat a parent row once per
        child.
        """
        return False
