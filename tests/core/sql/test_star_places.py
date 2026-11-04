"""Stars stand only as top-level projections or in COUNT(*) (R28); outer scopes (fix 3)."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import DIALECTS, Outcome, PolicyRun, summary

NNA = Reason.NODE_NOT_ALLOWED

CASES: list[tuple[str, Outcome]] = [
    # a nested `t.*` is the whole row on PostgreSQL
    ("SELECT CAST(p.* AS TEXT) FROM people p", NNA),
    ("SELECT coalesce(p.*) FROM people p", NNA),
    ("SELECT length(p.*) FROM people p", NNA),
    ("SELECT p.id FROM people p WHERE p.* IS NULL", NNA),
    ("SELECT p.id FROM people p WHERE p.* = p.*", NNA),
    ("SELECT p.id FROM people p JOIN orders o ON o.* = p.*", NNA),
    ("SELECT count(*) FROM people p GROUP BY p.*", NNA),
    ("SELECT count(p.*) FROM people p", NNA),
    ("SELECT count(DISTINCT p.*) FROM people p", NNA),
    ("SELECT (p.*) FROM people p", NNA),
    ("SELECT (*) FROM people", NNA),
    ("SELECT p.* AS x FROM people p", NNA),
    ("SELECT city FROM people p GROUP BY city ORDER BY count(p.*)", NNA),
    ("SELECT city FROM people p GROUP BY city ORDER BY count(DISTINCT p.*)", NNA),
    ("SELECT id FROM people WHERE EXISTS (SELECT 1 FROM orders o WHERE o.* IS NULL)", NNA),
    # allowed stars
    ("SELECT * FROM people", ([], 0, 0)),
    ("SELECT p.*, o.id FROM people p JOIN orders o ON o.customer_name = p.full_name", ([], 0, 0)),
    ("SELECT count(*) FROM people", ([], 0, 0)),
    ("SELECT city FROM people GROUP BY city ORDER BY count(*) DESC", ([], 0, 0)),
    (
        "SELECT id FROM people WHERE EXISTS (SELECT * FROM orders o WHERE o.id = people.id)",
        ([], 0, 0),
    ),
    # a derived table inside a correlated subquery sees the subquery's outer query
    ("SELECT (SELECT d.x FROM (SELECT p.full_name AS x) d) FROM people p", ([0], 0, 0)),
    ("SELECT (SELECT d.city FROM (SELECT p.id AS city) d) FROM people p", Reason.AMBIGUOUS_COLUMN),
    (
        (
            "SELECT (SELECT e.city FROM (WITH c AS (SELECT p.id AS city) SELECT c.city FROM c) e) "
            "FROM people p"
        ),
        Reason.AMBIGUOUS_COLUMN,
    ),
    # a derived table at the top level does not
    (
        "SELECT d.n FROM (SELECT count(*) AS n FROM orders) d JOIN people p ON p.id = d.n",
        ([], 0, 0),
    ),
    (
        "SELECT d.city FROM (SELECT count(*) AS city FROM orders) d JOIN people p ON p.id = d.city",
        ([], 0, 0),
    ),
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "expected"), CASES)
def test_star_and_scope(policy: PolicyRun, dialect: str, sql: str, expected: Outcome) -> None:
    assert summary(policy(sql, dialect)) == expected
