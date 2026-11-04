"""Where the random tiebreak goes: cut queries, value subqueries, wrapped set operations."""

import pytest

from incognito_sql.core.errors import Reason, Rejection

from .conftest import DIALECTS, PrepareRun


def test_offset_alone_cuts_rows(prepare_sql: PrepareRun) -> None:
    sql = prepare_sql("SELECT n.id FROM (SELECT id FROM orders ORDER BY id OFFSET 1) AS n").sql
    assert "FROM orders ORDER BY id, RANDOM() OFFSET 1) AS n ORDER BY RANDOM()" in sql


@pytest.mark.parametrize("dialect", DIALECTS)
def test_subquery_in_a_value_list_is_a_value(prepare_sql: PrepareRun, dialect: str) -> None:
    sql = prepare_sql("SELECT id FROM people WHERE id IN ((SELECT id FROM orders), 3)", dialect).sql
    assert "IN ((SELECT orders.id AS id FROM orders ORDER BY RANDOM()" in sql


def test_wrapper_takes_over_the_offset(prepare_sql: PrepareRun) -> None:
    sql = prepare_sql("SELECT id FROM people UNION SELECT id FROM orders OFFSET 1").sql
    assert sql.endswith(") AS _q0 ORDER BY RANDOM() OFFSET 1")


def test_expanded_star_is_wrapped_by_its_column_names(prepare_sql: PrepareRun) -> None:
    sql = prepare_sql("SELECT DISTINCT p.* FROM people p ORDER BY p.city").sql
    assert sql == (
        "SELECT _q0.id, _q0.full_name, _q0.phone, _q0.city FROM (SELECT DISTINCT p.id,"
        " p.full_name, p.phone, p.city FROM people AS p) AS _q0 ORDER BY _q0.city, RANDOM()"
    )


def test_wrap_key_must_be_an_output_of_its_query(prepare_sql: PrepareRun) -> None:
    with pytest.raises(Rejection) as exc:
        prepare_sql(
            "SELECT DISTINCT o.id, p.city FROM orders o JOIN people p ON p.id = o.id "
            "ORDER BY p.id LIMIT 2"
        )
    assert exc.value.reason is Reason.NODE_NOT_ALLOWED


def test_each_wrapper_gets_a_fresh_alias(prepare_sql: PrepareRun) -> None:
    sql = prepare_sql(
        "SELECT a.id FROM (SELECT DISTINCT id FROM people LIMIT 2) a "
        "JOIN (SELECT DISTINCT id FROM orders LIMIT 2) b ON a.id = b.id"
    ).sql
    assert "FROM people) AS _q0 ORDER BY" in sql
    assert "FROM orders) AS _q1 ORDER BY" in sql


def test_wrapper_alias_skips_every_taken_name(prepare_sql: PrepareRun) -> None:
    sql = prepare_sql(
        "SELECT DISTINCT _q0.id FROM people _q0 JOIN people _q1 ON _q0.id = _q1.id"
    ).sql
    assert sql.endswith(") AS _q2 ORDER BY RANDOM()")
