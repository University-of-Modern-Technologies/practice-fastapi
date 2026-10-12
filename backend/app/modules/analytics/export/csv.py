"""Renders a table of rows as CSV.

Rows already carry values in their published wire form — a money figure is
already the two-decimal string the JSON report would show, a timestamp is
already an ISO string — so nothing here reformats a value, only escapes it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

#: RFC 4180 line ending, used after the header and after every row.
_LINE_END = "\r\n"

_NEEDS_QUOTING = ('"', ",", "\r", "\n")


def _escape_field(value: str) -> str:
    if any(character in value for character in _NEEDS_QUOTING):
        return '"' + value.replace('"', '""') + '"'
    return value


#: A cell a spreadsheet would read as a formula: one that opens with `=`, `+`,
#: `-` or `@`, or with a tab or carriage return that some of them skip before
#: looking. A product name or an owner's name is typed by a person, and a file
#: that runs `=HYPERLINK(...)` when a manager opens it is the export doing the
#: attacker's work.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")

#: A plain decimal — a count, an amount, a rate — which a spreadsheet reads as
#: a number whatever its sign. It is left exactly as the report rendered it:
#: prefixing `-12.50` would turn a figure into text and protect nothing.
_PLAIN_NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")


def _neutralise_formula(text: str) -> str:
    """Makes a would-be formula literal, by the convention spreadsheets honour.

    A leading apostrophe tells the spreadsheet the rest is text.
    """
    if text.startswith(_FORMULA_TRIGGERS) and _PLAIN_NUMBER.fullmatch(text) is None:
        return "'" + text
    return text


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        # `str(True)` is `"True"`; the wire form the report already used is lowercase.
        return "true" if value else "false"
    return _neutralise_formula(str(value))


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
