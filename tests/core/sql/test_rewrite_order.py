"""A random tiebreak hides the database's row order wherever rows are cut or capped."""

import pytest

from incognito_sql.core.errors import Reason, Rejection

from .conftest import DIALECTS, PrepareRun

RAND = "RANDOM()"

# (sql, number of random keys)
CASES: list[tuple[str, int]] = [
    ("SELECT full_name FROM people", 1),
    ("SELECT id, city FROM people", 1),
    ("SELECT id, full_name FROM people ORDER BY 1", 1),
    ("SELECT city, count(*) FROM people GROUP BY full_name, city", 1),
    ("SELECT city, count(*) FROM people GROUP BY city", 1),
    ("SELECT id FROM people WHERE full_name IN (SELECT customer_name FROM orders LIMIT 1)", 2),
    ("SELECT id FROM people WHERE id IN (SELECT id FROM orders LIMIT 1)", 2),
    ("SELECT d.id FROM (SELECT id, full_name FROM people LIMIT 3 OFFSET 1) d", 2),
    ("SELECT d.id FROM (SELECT id FROM people GROUP BY full_name, id LIMIT 3) d", 2),
    ("SELECT d.n FROM (SELECT count(*) AS n FROM people GROUP BY city LIMIT 1) d", 2),
    ("SELECT full_name FROM people UNION SELECT customer_name FROM orders", 1),
    ("SELECT id FROM people UNION SELECT id FROM orders", 1),
    ("SELECT DISTINCT full_name, city FROM people ORDER BY city LIMIT 2", 1),
    ("SELECT (SELECT o.customer_name FROM orders o WHERE o.id = p.id) FROM people p", 2),
    ("SELECT id FROM people WHERE id IN (SELECT id FROM orders)", 1),
    ("SELECT id FROM people p WHERE EXISTS (SELECT 1 FROM orders o WHERE o.id = p.id)", 1),
    ("SELECT d.id FROM (SELECT id FROM people) d", 1),
    ("SELECT id FROM people WHERE id = ((SELECT max(id) FROM orders))", 2),
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "count"), CASES)
def test_random_tiebreak(prepare_sql: PrepareRun, dialect: str, sql: str, count: int) -> None:
    assert prepare_sql(sql, dialect).sql.count(RAND) == count


def test_tiebreak_is_the_last_key(prepare_sql: PrepareRun) -> None:
    sql = prepare_sql("SELECT id, full_name FROM people ORDER BY 1 DESC").sql
    assert sql.endswith("ORDER BY id DESC, RANDOM()")


@pytest.mark.parametrize("dialect", DIALECTS)
def test_union_is_wrapped(prepare_sql: PrepareRun, dialect: str) -> None:
    sql = prepare_sql(
        "SELECT full_name, city FROM people UNION SELECT customer_name, note FROM orders "
        "ORDER BY 2 DESC LIMIT 3",
        dialect,
    ).sql
    assert sql.startswith("SELECT _q0.full_name, _q0.city FROM (SELECT people.full_name")
    assert ") AS _q0 ORDER BY _q0.city DESC, RANDOM()" in sql
    assert sql.endswith(" LIMIT 3")


def test_distinct_is_wrapped(prepare_sql: PrepareRun) -> None:
    sql = prepare_sql("SELECT DISTINCT full_name, city FROM people ORDER BY city LIMIT 2").sql
    assert sql == (
        "SELECT _q0.full_name, _q0.city FROM (SELECT DISTINCT people.full_name AS full_name,"
        " people.city AS city FROM people) AS _q0 ORDER BY _q0.city, RANDOM() LIMIT 2"
    )


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    ("sql", "tail"),
    [
        (
            "SELECT d.id FROM (SELECT DISTINCT id, full_name FROM people LIMIT 3) AS d",
            "FROM people) AS _q0 ORDER BY RANDOM()",
        ),
        ("SELECT DISTINCT city, full_name FROM people ORDER BY (1)", "ORDER BY _q0.city, RANDOM()"),
        (
            "SELECT DISTINCT city, count(*) FROM people GROUP BY city, full_name ORDER BY count(*)",
            "ORDER BY _q0._col_1, RANDOM()",
        ),
    ],
)
def test_wrap_keys(prepare_sql: PrepareRun, dialect: str, sql: str, tail: str) -> None:
    assert tail in prepare_sql(sql, dialect).sql


def test_wrap_with_key_outside_the_output_is_refused(prepare_sql: PrepareRun) -> None:
    with pytest.raises(Rejection) as exc:
        prepare_sql("SELECT DISTINCT full_name FROM people ORDER BY id", "sqlite")
    assert exc.value.reason is Reason.NODE_NOT_ALLOWED


def test_wrapper_alias_avoids_taken_names(prepare_sql: PrepareRun) -> None:
    sql = prepare_sql(
        "SELECT _q0.full_name FROM people _q0 UNION SELECT customer_name FROM orders"
    ).sql
    assert ") AS _q1 ORDER BY RANDOM()" in sql


def test_wrap_with_duplicate_output_names_is_refused(prepare_sql: PrepareRun) -> None:
    with pytest.raises(Rejection) as exc:
        prepare_sql(
            "SELECT DISTINCT p.id, o.id, p.full_name FROM people p JOIN orders o ON o.id = p.id"
        )
    assert exc.value.reason is Reason.AMBIGUOUS_COLUMN


@pytest.mark.parametrize(
    ("sql", "ordered"),
    [
        ("SELECT id, city FROM people ORDER BY city DESC, id", True),
        ("SELECT id FROM people UNION SELECT id FROM orders ORDER BY 1", True),
        ("SELECT DISTINCT city FROM people ORDER BY city", True),
        ("SELECT id, city FROM people", False),
        ("SELECT d.id FROM (SELECT id FROM people ORDER BY id LIMIT 2) AS d", False),
    ],
)
@pytest.mark.parametrize("dialect", DIALECTS)
def test_outer_order_is_reported(
    prepare_sql: PrepareRun, dialect: str, sql: str, *, ordered: bool
) -> None:
    assert prepare_sql(sql, dialect).ordered is ordered
