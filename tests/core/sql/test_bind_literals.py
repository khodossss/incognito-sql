"""Which literals become binds, and how a compared one finds its identifier."""

import pytest

from .conftest import DIALECTS, PrepareRun


@pytest.mark.parametrize("dialect", DIALECTS)
def test_every_comparison_is_rewritten_after_one_without_identifier(
    prepare_sql: PrepareRun, dialect: str
) -> None:
    p = prepare_sql("SELECT id FROM people WHERE id = 1 AND full_name = 'Zq One'", dialect)
    assert "people.full_name IN (:p0)" in p.sql
    assert p.params == {"p0": "Zq One", "p1": 1}


@pytest.mark.parametrize("dialect", DIALECTS)
def test_parenthesized_row_limit_stays_syntax(prepare_sql: PrepareRun, dialect: str) -> None:
    p = prepare_sql("SELECT id FROM people LIMIT (5) OFFSET (2)", dialect)
    assert "LIMIT (5) OFFSET (2)" in p.sql
    assert p.params == {}


@pytest.mark.parametrize("dialect", DIALECTS)
def test_identifier_may_stand_in_the_list(prepare_sql: PrepareRun, dialect: str) -> None:
    p = prepare_sql("SELECT id FROM people WHERE 'Zq One' IN (full_name)", dialect)
    assert list(p.params.values()) == ["Zq One"]
    assert "Zq" not in p.sql
