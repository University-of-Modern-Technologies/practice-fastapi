"""Turns optional query filters into a ``WHERE`` clause.

Every list endpoint in this codebase repeats the same shape: for each optional
filter, append a predicate only if the caller actually supplied a value. Spelled
out by hand that is a run of ``if value is not None: conditions.append(...)``
lines, one per filter, repeated in every module. The trap in that hand-written
form is the temptation to test truthiness instead of presence — ``if value:``
silently drops a legitimate ``0`` or ``False`` — so every verb here checks
``is not None`` (or, for text, an explicit emptiness check) rather than
truthiness.

This builder does not know what a "filter" means for any particular resource;
it only knows how to turn a value that may or may not be present into zero or
one predicate, and to chain that across a whole query.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import ColumnElement, or_

_LIKE_ESCAPE = "\\"


def escape_like_term(term: str) -> str:
    """Escapes ``LIKE``/``ILIKE`` wildcards in a caller-supplied search term.

    Left unescaped, a search for ``%`` would match every row and a search for
    ``_`` would silently match one character too many.
    """
    return (
        term.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )


def _contains(column: Any, term: str, *, escape: bool) -> ColumnElement[bool]:
    if escape:
        return cast(
            "ColumnElement[bool]", column.ilike(f"%{escape_like_term(term)}%", escape=_LIKE_ESCAPE)
        )
    return cast("ColumnElement[bool]", column.ilike(f"%{term}%"))


class FilterBuilder:
    """Collects ``WHERE`` predicates, skipping the ones a filter left unset.

    Every method returns ``self`` so a service can spell its filters as one
    fluent expression and hand the result straight to ``.where(*criteria)``.
    """

    def __init__(self, conditions: Sequence[ColumnElement[bool]] = ()) -> None:
        self._conditions: list[ColumnElement[bool]] = list(conditions)

    def equals(self, column: Any, value: Any) -> FilterBuilder:
        """Exact match, skipped when the value is absent.

        ``is not None`` on purpose: a value of ``0`` or ``False`` is a filter
        the caller meant to apply, not an unset one.
        """
        if value is not None:
            self._conditions.append(column == value)
        return self

    def flag(self, column: Any, value: bool | None) -> FilterBuilder:
        """Exact match on a boolean column, via ``IS`` rather than ``=``.

        A dedicated verb because the classic falsy-value trap is sharpest
        here: ``False`` is exactly as valid a filter as ``True``.
        """
        if value is not None:
            self._conditions.append(column.is_(value))
        return self

    def text(self, column: Any, value: str | None) -> FilterBuilder:
        """Exact match on a string filter, treating an empty string as absent.

        The same rule ``search`` uses: a blank field is a filter the caller
        never actually set, not an instruction to match an empty column.
        """
        if value:
            self._conditions.append(column == value)
        return self

    def search(
        self, term: str | None, columns: Sequence[Any], *, escape: bool = False
    ) -> FilterBuilder:
        """Case-insensitive substring match, ``OR``-ed across one or more columns.

        An empty string is treated as absent: it would otherwise compile to a
        predicate that matches every row, which is never what a caller who
        left the field blank intended.
        """
        if not term:
            return self
        clauses = [_contains(column, term, escape=escape) for column in columns]
        self._conditions.append(clauses[0] if len(clauses) == 1 else or_(*clauses))
        return self

    def range(self, column: Any, minimum: Any = None, maximum: Any = None) -> FilterBuilder:
        """Inclusive bounds, each applied only if the caller supplied it.

        A one-sided range — only a floor or only a ceiling — is exactly the
        case that falls out of applying the two bounds independently.
        """
        if minimum is not None:
            self._conditions.append(column >= minimum)
        if maximum is not None:
            self._conditions.append(column <= maximum)
        return self

    def add(self, condition: ColumnElement[bool] | None) -> FilterBuilder:
        """Escape hatch for a predicate none of the verbs above express."""
        if condition is not None:
            self._conditions.append(condition)
        return self

    def build(self) -> list[ColumnElement[bool]]:
        return self._conditions
