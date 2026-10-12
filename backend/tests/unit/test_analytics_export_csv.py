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


def test_neutralises_a_cell_that_would_be_read_as_a_formula() -> None:
    """A leading apostrophe makes a would-be formula literal."""
    rows = [
        {"name": '=HYPERLINK("http://x","y")', "amount": "1.00"},
        {"name": "+1+1", "amount": "2.00"},
        {"name": "@SUM(A1)", "amount": "3.00"},
        {"name": "-cmd", "amount": "4.00"},
        {"name": "\tTab", "amount": "5.00"},
        {"name": "\rReturn", "amount": "6.00"},
    ]

    assert render_csv(COLUMNS, rows) == (
        "name,amount\r\n"
        '"\'=HYPERLINK(""http://x"",""y"")",1.00\r\n'
        "'+1+1,2.00\r\n"
        "'@SUM(A1),3.00\r\n"
        "'-cmd,4.00\r\n"
        "'\tTab,5.00\r\n"
        '"\'\rReturn",6.00\r\n'
    )


def test_leaves_a_negative_number_a_number() -> None:
    assert render_csv(COLUMNS, [{"name": "-12", "amount": "-0.50"}]) == (
        "name,amount\r\n-12,-0.50\r\n"
    )


def test_renders_a_whole_rate_as_the_report_published_it() -> None:
    """The row arrives in its JSON form, where a whole rate is ``1``."""
    assert render_csv(("winRate",), [{"winRate": 1}, {"winRate": 0.25}]) == (
        "winRate\r\n1\r\n0.25\r\n"
    )
