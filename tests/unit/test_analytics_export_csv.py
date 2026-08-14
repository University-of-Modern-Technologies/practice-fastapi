"""`render_csv`: RFC 4180 escaping and the empty-table case."""

from __future__ import annotations

from app.modules.analytics.export.csv import render_csv

COLUMNS = ("name", "amount")


def test_quotes_a_field_carrying_a_comma_a_double_quote_or_a_newline() -> None:
    csv = render_csv(
        COLUMNS,
        [
            {"name": "a, b", "amount": "1.00"},
            {"name": 'he said "hi"', "amount": "2.00"},
            {"name": "line1\nline2", "amount": "3.00"},
        ],
    )

    assert csv == ('name,amount\r\n"a, b",1.00\r\n"he said ""hi""",2.00\r\n"line1\nline2",3.00\r\n')


def test_renders_only_the_header_for_an_empty_table() -> None:
    assert render_csv(COLUMNS, []) == "name,amount\r\n"


def test_leaves_a_plain_field_unquoted() -> None:
    rows = [{"name": "plain", "amount": "10.00"}]
    assert render_csv(COLUMNS, rows) == "name,amount\r\nplain,10.00\r\n"


def test_renders_a_missing_or_none_cell_as_an_empty_field() -> None:
    assert render_csv(("value",), [{}]) == "value\r\n\r\n"
    assert render_csv(("value",), [{"value": None}]) == "value\r\n\r\n"
