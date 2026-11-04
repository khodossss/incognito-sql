"""R32: next to an aggregate or GROUP BY, a column outside an aggregate must be grouped."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import DIALECTS, Outcome, PolicyRun, summary

NNA = Reason.NODE_NOT_ALLOWED
UNK = Reason.UNKNOWN_COLUMN
OK: Outcome = ([], 0, 0)

CASES: list[tuple[str, Outcome]] = [
    ("SELECT id, count(*) FROM people", NNA),
    ("SELECT d.id FROM (SELECT id, count(*) AS n FROM people) d", NNA),
    ("SELECT city, count(*) FROM people GROUP BY city HAVING id > 1", NNA),
    ("SELECT city FROM people GROUP BY city ORDER BY id", NNA),
    ("SELECT city, id FROM people GROUP BY city", NNA),
    ("SELECT city, count(*) FROM people GROUP BY (1)", NNA),
    ("SELECT p.city, count(*) FROM people p JOIN people q ON q.id = p.id GROUP BY q.city", NNA),
    ("SELECT id + amount, count(*) FROM orders GROUP BY id", NNA),
    ("SELECT id + 1, count(*) FROM people GROUP BY id", OK),
    ("SELECT city, count(*) FROM people GROUP BY city", OK),
    ("SELECT city, count(*) AS n FROM people GROUP BY city ORDER BY n DESC", OK),
    ("SELECT city FROM people GROUP BY city HAVING count(*) > 1 ORDER BY city", OK),
    ("SELECT substring(city, 1, 2), count(*) FROM people GROUP BY 1", OK),
    ("SELECT count(*) FROM people GROUP BY (1)", OK),
    ("SELECT max(id), count(DISTINCT full_name) FROM people", OK),
    ("SELECT city, (SELECT count(*) FROM orders) FROM people GROUP BY city", OK),
    # a nested query reading the aggregating query's row (bypass 1)
    (
        (
            "SELECT count(*) AS n, (SELECT q.full_name FROM people q WHERE q.id = p.id) AS v "
            "FROM people p"
        ),
        NNA,
    ),
    (
        (
            "SELECT d.v FROM (SELECT count(*) AS n, (SELECT q.full_name FROM people q "
            "WHERE q.id = p.id) AS v FROM people p) d"
        ),
        NNA,
    ),
    (
        (
            "SELECT count(*), EXISTS (SELECT 1 FROM people q WHERE q.id = p.id AND q.id > 85) "
            "FROM people p"
        ),
        NNA,
    ),
    (
        (
            "SELECT count(*) FROM people p "
            "HAVING EXISTS (SELECT 1 FROM people q WHERE q.id = p.id AND q.id > 85)"
        ),
        NNA,
    ),
    (
        (
            "SELECT p.city, (SELECT count(*) FROM orders o WHERE o.note = p.city) "
            "FROM people p GROUP BY p.city"
        ),
        OK,
    ),
    # an aggregate over outer columns only aggregates the outer query (bypass 2)
    (
        (
            "SELECT (SELECT count(p.id) FROM orders o WHERE o.id = 100) AS c, p.full_name "
            "FROM people p"
        ),
        NNA,
    ),
    ("SELECT (SELECT count(o.id) FROM orders o WHERE o.id = p.id) FROM people p", OK),
    ("SELECT (SELECT max(o.id + p.id) FROM orders o) FROM people p", OK),
    # an outer column at any depth of the argument moves the aggregate outward (B2)
    (
        (
            "SELECT (SELECT count((SELECT p.id)) "
            "FROM orders o WHERE o.id = 1) AS c, p.id FROM people p"
        ),
        NNA,
    ),
    (
        (
            "SELECT (SELECT count((SELECT p.full_name)) "
            "FROM orders o WHERE o.id = 1) AS c, p.full_name FROM people p"
        ),
        NNA,
    ),
    (
        (
            "SELECT (SELECT count(EXISTS (SELECT 1 FROM orders o2 WHERE o2.id = p.id)) "
            "FROM orders o WHERE o.id = 1) AS c, p.id FROM people p"
        ),
        NNA,
    ),
    (
        (
            "SELECT d.c, d.i FROM (SELECT (SELECT count((SELECT p.id)) "
            "FROM orders o WHERE o.id = 1) AS c, p.id AS i FROM people p) d"
        ),
        NNA,
    ),
    (
        (
            "SELECT (SELECT max((SELECT p.id + 0)) "
            "FROM orders o WHERE o.id = 1) AS c, p.id FROM people p"
        ),
        NNA,
    ),
    # no outer column, or a column of the holding query: the aggregate stays put
    (
        ("SELECT (SELECT max(1) FROM orders o WHERE o.id = 1) AS c, p.id FROM people p"),
        OK,
    ),
    (
        ("SELECT (SELECT count(1) FROM orders o WHERE o.id = 1) AS c, p.id FROM people p"),
        OK,
    ),
    (
        ("SELECT (SELECT count((SELECT 1)) FROM orders o WHERE o.id = 1) AS c, p.id FROM people p"),
        OK,
    ),
    (
        (
            "SELECT (SELECT max(o.id * 0 + p.id) "
            "FROM orders o WHERE o.id = 1) AS c, p.id FROM people p"
        ),
        OK,
    ),
    (
        (
            "SELECT (SELECT count((SELECT o2.id FROM orders o2 LIMIT 1)) "
            "FROM orders o WHERE o.id = 1) AS c, p.id FROM people p"
        ),
        OK,
    ),
    ("SELECT max((SELECT p.id + 0)) FROM people p", OK),
    # a set operation's ORDER BY has no range variable to aggregate
    ("SELECT id FROM people UNION ALL SELECT id FROM orders ORDER BY max(people.id)", UNK),
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "expected"), CASES)
def test_grouping(policy: PolicyRun, dialect: str, sql: str, expected: Outcome) -> None:
    assert summary(policy(sql, dialect)) == expected
