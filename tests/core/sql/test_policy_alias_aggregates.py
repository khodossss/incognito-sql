"""R35: an output alias named inside an aggregate is refused."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import DIALECTS, Outcome, PolicyRun, summary

NNA = Reason.NODE_NOT_ALLOWED
OK: Outcome = ([], 0, 0)

CASES: list[tuple[str, Outcome]] = [
    # SQLite reads `x` as the alias and so aggregates the outer query
    (
        (
            "SELECT (SELECT p.id AS x FROM orders o WHERE o.id = 1 ORDER BY count(x)) AS c, "
            "p.full_name FROM people p"
        ),
        NNA,
    ),
    (
        (
            "SELECT (SELECT p.id AS x FROM orders o WHERE o.id = 1 ORDER BY count(x)) AS c, "
            "p.id FROM people p"
        ),
        NNA,
    ),
    (
        (
            "SELECT (SELECT (SELECT p.id) AS x FROM orders o WHERE o.id = 1 "
            "ORDER BY count(x)) AS c, p.full_name FROM people p"
        ),
        NNA,
    ),
    (
        (
            "SELECT (SELECT p.id + 0 AS x FROM orders o WHERE o.id = 1 ORDER BY count(x)) AS c, "
            "p.full_name FROM people p"
        ),
        NNA,
    ),
    (
        (
            "SELECT d.c, d.i FROM (SELECT (SELECT p.id AS x FROM orders o WHERE o.id = 1 "
            "ORDER BY count(x)) AS c, p.full_name AS i FROM people p) d"
        ),
        NNA,
    ),
    ("SELECT city AS c, count(*) AS n FROM people GROUP BY city ORDER BY max(c)", NNA),
    # no alias inside the aggregate
    (
        (
            "SELECT (SELECT p.id AS x FROM orders o WHERE o.id = 1 ORDER BY count(*)) AS c, "
            "p.full_name FROM people p"
        ),
        ([1], 0, 0),
    ),
    (
        (
            "SELECT (SELECT p.id AS x FROM orders o WHERE o.id = 1 ORDER BY count(o.id)) AS c, "
            "p.full_name FROM people p"
        ),
        ([1], 0, 0),
    ),
    ("SELECT city AS c, count(*) AS n FROM people GROUP BY city ORDER BY n", OK),
    # a qualified column named like an output is that column, not the alias
    ("SELECT city, count(city) FROM people GROUP BY city", OK),
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "expected"), CASES)
def test_alias_in_aggregate(policy: PolicyRun, dialect: str, sql: str, expected: Outcome) -> None:
    assert summary(policy(sql, dialect)) == expected


@pytest.mark.parametrize("dialect", DIALECTS)
def test_qualified_sort_key_named_like_an_alias_is_still_grouped(
    policy: PolicyRun, dialect: str
) -> None:
    # Only a bare name stands for the output alias; `o.amount` is an ungrouped column.
    sql = (
        "SELECT p.city AS amount FROM people p JOIN orders o ON o.id = p.id "
        "GROUP BY p.city ORDER BY o.amount"
    )
    assert policy(sql, dialect) is Reason.AMBIGUOUS_COLUMN
    assert policy(sql, dialect, nodes=False) is NNA
