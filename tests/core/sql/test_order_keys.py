"""ORDER BY keys are closed shapes (R27); positions and aliases cannot shift lineage."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import DIALECTS, Outcome, PolicyRun, summary

NNA = Reason.NODE_NOT_ALLOWED
SORT_BY_LIKE = (
    "SELECT o.id AS x FROM orders o "
    "ORDER BY CASE WHEN full_name LIKE 'A%' THEN o.id ELSE -o.id END LIMIT 1"
)
DERIVED = "SELECT d.id FROM (SELECT full_name, id FROM people ORDER BY {} LIMIT 1) d"

CASES: list[tuple[str, Outcome]] = [
    # correlated name inside a sort expression (binds to the outer people.full_name)
    (f"SELECT ({SORT_BY_LIKE}) FROM people", NNA),  # noqa: S608
    (f"SELECT (SELECT ({SORT_BY_LIKE})) FROM people", NNA),  # noqa: S608
    (f"SELECT p.id FROM people p WHERE p.id IN ({SORT_BY_LIKE})", NNA),  # noqa: S608
    (
        (
            "SELECT (SELECT o.id AS full_name FROM orders o "
            "ORDER BY CASE WHEN full_name LIKE 'A%' THEN o.id ELSE -o.id END LIMIT 1) FROM people"
        ),
        NNA,
    ),
    # an alias equal to a column of an enclosing query (R26 a, extended)
    (
        "SELECT (SELECT o.id AS full_name FROM orders o ORDER BY full_name LIMIT 1) FROM people",
        Reason.AMBIGUOUS_COLUMN,
    ),
    (
        "SELECT p.id FROM people p WHERE EXISTS (SELECT o.id AS city FROM orders o)",
        Reason.AMBIGUOUS_COLUMN,
    ),
    (
        "SELECT d.n FROM (SELECT count(*) AS n FROM orders) d JOIN people p ON p.id = d.n",
        ([], 0, 0),
    ),
    # negated or signed positions
    (DERIVED.format("- -1"), NNA),
    (DERIVED.format("-(-1)"), NNA),
    (DERIVED.format("(-(-(1)))"), NNA),
    (DERIVED.format("-(+(-1))"), NNA),
    (DERIVED.format("- -2"), NNA),
    (DERIVED.format("'1'"), NNA),
    (DERIVED.format("1.0"), NNA),
    # positions shifted by a star
    ("SELECT *, id FROM people ORDER BY (2)", NNA),
    ("SELECT *, id FROM people ORDER BY 2", NNA),
    ("SELECT p.*, p.id FROM people p ORDER BY 2", NNA),
    ("SELECT DISTINCT *, id FROM people ORDER BY 2", NNA),
    ("SELECT p.*, o.id FROM people p JOIN orders o ON o.id = p.id ORDER BY 2", NNA),
    ("SELECT *, id FROM people GROUP BY 2", NNA),
    # other expressions as sort keys
    ("SELECT city FROM people ORDER BY upper(city)", NNA),
    ("SELECT city FROM people ORDER BY (SELECT 1)", NNA),
    ("SELECT city FROM people ORDER BY coalesce(city, 'x')", NNA),
    ("SELECT city FROM people GROUP BY city ORDER BY count(DISTINCT upper(city))", NNA),
    # allowed keys
    ("SELECT city, count(*) FROM people GROUP BY city ORDER BY count(*) DESC", ([], 0, 0)),
    ("SELECT city, id FROM people ORDER BY city, 2", ([], 0, 0)),
    ("SELECT o.id FROM orders o ORDER BY o.amount", ([], 0, 0)),
    ("SELECT * FROM people ORDER BY id", ([], 0, 0)),
    ("SELECT city FROM people GROUP BY city ORDER BY count(DISTINCT full_name)", ([], 0, 0)),
    ("SELECT city FROM people GROUP BY city ORDER BY max(id), sum(id), avg(id)", ([], 0, 0)),
    ("SELECT city FROM people GROUP BY city ORDER BY min(full_name)", Reason.PII_OPERATION),
    ("SELECT city FROM people GROUP BY city ORDER BY count(full_name)", Reason.PII_OPERATION),
    # parenthesised ordinals
    ("SELECT full_name FROM people ORDER BY (1)", Reason.PII_OPERATION),
    ("SELECT full_name FROM people ORDER BY ((1)) DESC", Reason.PII_OPERATION),
    (
        (
            "SELECT id FROM people WHERE full_name IN "
            "(SELECT full_name FROM people ORDER BY (1) LIMIT 1)"
        ),
        Reason.PII_OPERATION,
    ),
    ("SELECT (SELECT full_name FROM people ORDER BY (1) LIMIT 1)", Reason.PII_OPERATION),
    (
        "SELECT full_name FROM people UNION SELECT customer_name FROM orders ORDER BY (1)",
        Reason.PII_OPERATION,
    ),
    ("SELECT id, full_name FROM people ORDER BY (1)", ([1], 0, 0)),
    ("SELECT full_name FROM people ORDER BY (3)", Reason.UNKNOWN_COLUMN),
    ("SELECT full_name FROM people ORDER BY (2)", Reason.UNKNOWN_COLUMN),
    ("SELECT full_name FROM people ORDER BY (0)", Reason.NODE_NOT_ALLOWED),
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "expected"), CASES)
def test_order_key(policy: PolicyRun, dialect: str, sql: str, expected: Outcome) -> None:
    assert summary(policy(sql, dialect)) == expected
