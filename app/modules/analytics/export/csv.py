"""Renders a table of rows as CSV.

Rows already carry values in their published wire form — a money figure is
already the two-decimal string the JSON report would show, a timestamp is
already an ISO string — so nothing here reformats a value, only escapes it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: RFC 4180 line ending, used after the header and after every row.
_LINE_END = "\r\n"

_NEEDS_QUOTING = ('"', ",", "\r", "\n")


def _escape_field(value: str) -> str:
    if any(character in value for character in _NEEDS_QUOTING):
        return '"' + value.replace('"', '""') + '"'
    return value


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        # `str(True)` is `"True"`; the wire form the report already used is lowercase.
        return "true" if value else "false"
    return str(value)


def render_csv(columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> str:
    """Renders `rows` as CSV: comma-separated, RFC 4180 quoting, CRLF endings.

    An empty `rows` still yields the header line, so an empty report downloads
    as a file a spreadsheet can open rather than an empty blob.
    """
    header = ",".join(_escape_field(column) for column in columns)
    body = (
        ",".join(_escape_field(_cell_text(row.get(column))) for column in columns) for row in rows
    )
    return "".join(line + _LINE_END for line in (header, *body))
