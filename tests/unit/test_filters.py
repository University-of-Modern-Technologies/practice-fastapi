"""``FilterBuilder``: which values become a predicate, and which are skipped."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnClause, column

from app.core.filters import FilterBuilder, escape_like_term

NAME: ColumnClause[Any] = column("name")
CATEGORY: ColumnClause[Any] = column("category")
EMAIL: ColumnClause[Any] = column("email")
IS_ACTIVE: ColumnClause[Any] = column("is_active")
QUANTITY: ColumnClause[Any] = column("quantity")
AMOUNT: ColumnClause[Any] = column("amount")


def sql(condition: object) -> str:
    return str(condition)


def test_none_is_skipped_by_equals() -> None:
    criteria = FilterBuilder().equals(CATEGORY, None).build()

    assert criteria == []


def test_an_empty_string_is_skipped_by_search() -> None:
    criteria = FilterBuilder().search("", [NAME]).build()

    assert criteria == []


def test_an_empty_string_is_skipped_by_text() -> None:
    criteria = FilterBuilder().text(CATEGORY, "").build()

    assert criteria == []


def test_zero_is_a_real_filter_not_an_absent_one() -> None:
    """The classic falsy-value trap: ``0`` is a value the caller chose."""
    criteria = FilterBuilder().equals(QUANTITY, 0).build()

    assert len(criteria) == 1
    assert "quantity = " in sql(criteria[0])


def test_false_is_a_real_filter_not_an_absent_one() -> None:
    criteria = FilterBuilder().flag(IS_ACTIVE, False).build()

    assert len(criteria) == 1
    assert "is_active IS " in sql(criteria[0])


def test_flag_none_is_skipped() -> None:
    criteria = FilterBuilder().flag(IS_ACTIVE, None).build()

    assert criteria == []


def test_a_range_with_only_a_floor_omits_the_ceiling() -> None:
    criteria = FilterBuilder().range(AMOUNT, minimum=10).build()

    assert len(criteria) == 1
    assert ">=" in sql(criteria[0])


def test_a_range_with_only_a_ceiling_omits_the_floor() -> None:
    criteria = FilterBuilder().range(AMOUNT, maximum=10).build()

    assert len(criteria) == 1
    assert "<=" in sql(criteria[0])


def test_a_range_with_both_bounds_produces_both_predicates() -> None:
    criteria = FilterBuilder().range(AMOUNT, minimum=1, maximum=10).build()

    assert len(criteria) == 2


def test_a_range_with_neither_bound_produces_nothing() -> None:
    criteria = FilterBuilder().range(AMOUNT, None, None).build()

    assert criteria == []


def test_search_across_several_fields_is_ored_together() -> None:
    criteria = FilterBuilder().search("byron", [NAME, EMAIL]).build()

    assert len(criteria) == 1
    statement = sql(criteria[0])
    assert "lower(name)" in statement
    assert "lower(email)" in statement
    assert "OR" in statement


def test_search_over_a_single_field_skips_the_or() -> None:
    criteria = FilterBuilder().search("byron", [NAME]).build()

    assert len(criteria) == 1
    assert "OR" not in sql(criteria[0])


def test_an_escaped_search_neutralises_wildcards() -> None:
    assert escape_like_term("100%") == "100\\%"
    assert escape_like_term("a_b") == "a\\_b"


def test_conditions_seeded_at_construction_come_first() -> None:
    seed = CATEGORY == "hardware"

    criteria = FilterBuilder([seed]).equals(NAME, "widget").build()

    assert criteria[0] is seed
    assert len(criteria) == 2


def test_add_is_an_escape_hatch_for_an_arbitrary_predicate() -> None:
    criteria = FilterBuilder().add(CATEGORY == "hardware").build()

    assert len(criteria) == 1


def test_add_with_none_is_a_no_op() -> None:
    criteria = FilterBuilder().add(None).build()

    assert criteria == []
