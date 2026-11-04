"""R33: SUM and AVG take a bare column, so overflow cannot reveal the scan order."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import DIALECTS, Outcome, PolicyRun, summary

NNA = Reason.NODE_NOT_ALLOWED
OK: Outcome = ([], 0, 0)
CASES: list[tuple[str, Outcome]] = [
    ("SELECT sum(CASE WHEN id = 100 THEN 1e308 ELSE -1e308 END) FROM people", NNA),
    ("SELECT sum((id - 85.5) * 1e307) FROM people", NNA),
    ("SELECT avg(id + 1) FROM people", NNA),
    ("SELECT sum(DISTINCT id * 2) FROM people", NNA),
    ("SELECT sum(1) FROM people", NNA),
    ("SELECT city FROM people GROUP BY city ORDER BY sum(id * 1e307)", NNA),
    ("SELECT sum(id), avg(id) FROM people", OK),
    ("SELECT sum(DISTINCT o.amount), avg((o.amount)) FROM orders o", OK),
    ("SELECT count(id * 2), max(id + 1) FROM people", OK),
    # a derived or CTE column carries its expression into the sum (R33)
    (
        (
            "SELECT sum(d.x) FROM (SELECT CASE WHEN id = 100 THEN 1e308 WHEN id = 99 "
            "THEN 1e308 WHEN id = 71 THEN -1e308 ELSE 0 END AS x FROM people) d"
        ),
        NNA,
    ),
    ("SELECT avg(d.x) FROM (SELECT (id - 85.5) * 1e307 AS x FROM people) d", NNA),
    (
        (
            "SELECT sum(d.x) FROM (SELECT CASE WHEN id = 100 THEN 9223372036854775807 "
            "WHEN id = 99 THEN 1 WHEN id = 71 THEN -9223372036854775807 ELSE 0 END AS x "
            "FROM people) d"
        ),
        NNA,
    ),
    (
        (
            "SELECT sum(DISTINCT d.x) FROM "
            "(SELECT CASE WHEN id = 100 THEN 1 ELSE 1.0 END AS x FROM people) d"
        ),
        NNA,
    ),
    (
        (
            "WITH d AS (SELECT CASE WHEN id = 100 THEN 1e308 WHEN id = 99 THEN 1e308 "
            "WHEN id = 71 THEN -1e308 ELSE 0 END AS x FROM people) SELECT sum(d.x) FROM d"
        ),
        NNA,
    ),
    ("WITH d AS (SELECT (id - 85.5) * 1e307 AS x FROM people) SELECT avg(d.x) FROM d", NNA),
    (
        (
            "SELECT sum(e.x) FROM (SELECT d.x FROM (SELECT CASE WHEN id = 100 THEN 1e308 "
            "ELSE -1e308 END AS x FROM people) d) e"
        ),
        NNA,
    ),
    (
        "SELECT sum(u.x) FROM (SELECT id AS x FROM people UNION ALL SELECT id * 2 FROM orders) u",
        NNA,
    ),
    ("SELECT sum(d.n) FROM (SELECT count(*) AS n FROM people GROUP BY city) d", NNA),
    ("SELECT sum(d.x) FROM (SELECT id AS x, id AS x FROM people) d", NNA),
    (
        (
            "SELECT sum(u.x) FROM (SELECT id AS x, id AS x FROM people "
            "UNION ALL SELECT id, id FROM orders) u"
        ),
        NNA,
    ),
    (
        (
            "SELECT sum(u.y) FROM (SELECT id AS x, id AS y FROM people "
            "UNION ALL SELECT id FROM orders) u"
        ),
        NNA,
    ),
    ("SELECT sum(d.id) FROM (SELECT * FROM people p JOIN orders o ON o.id = p.id) d", NNA),
    ("SELECT id AS x FROM people GROUP BY id ORDER BY sum(x)", NNA),
    ("SELECT sum(coalesce(1, id)) FROM people", NNA),  # a function, not DISTINCT
    # the column names no range variable of the query holding the sum
    ("SELECT id FROM people UNION ALL SELECT id FROM orders ORDER BY sum(people.id)", NNA),
    # bare columns all the way down to a table column
    ("SELECT sum(d.x), avg(d.x) FROM (SELECT id AS x FROM people) d", OK),
    ("WITH c AS (SELECT o.amount FROM orders o) SELECT sum(DISTINCT c.amount) FROM c", OK),
    ("SELECT sum(e.x) FROM (SELECT d.x FROM (SELECT (id) AS x FROM people) d) e", OK),
    ("SELECT sum(d.amount) FROM (SELECT * FROM orders) d", OK),
    ("SELECT sum(u.x) FROM (SELECT id AS x FROM people UNION ALL SELECT id FROM orders) u", OK),
    # the summed column next to others: found by its own name or position
    ("SELECT sum(d.x) FROM (SELECT id AS x, city FROM people) d", OK),
    (
        (
            "SELECT sum(u.x) FROM (SELECT id AS x, city FROM people "
            "UNION ALL SELECT id, note FROM orders) u"
        ),
        OK,
    ),
    ("SELECT sum(d.id) FROM (SELECT o.* FROM orders o JOIN people p ON p.id = o.id) d", OK),
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "expected"), CASES)
def test_sum_avg_argument(policy: PolicyRun, dialect: str, sql: str, expected: Outcome) -> None:
    assert summary(policy(sql, dialect)) == expected
