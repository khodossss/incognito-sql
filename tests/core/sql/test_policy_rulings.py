"""Cases beyond the table: predicates, aggregates, ordering, unions, lineage."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import DIALECTS, Outcome, PolicyRun, summary

TK = "tk_abcdefghijklmnop"
OK: Outcome = ([], 0, 0)
NNA = Reason.NODE_NOT_ALLOWED

CASES: list[tuple[str, Outcome]] = [
    # predicates
    ("SELECT id FROM people WHERE NOT full_name = 'Ivan Petrov'", Reason.PII_OPERATION),
    ("SELECT id FROM people WHERE NOT (full_name IN ('Ivan Petrov'))", Reason.PII_OPERATION),
    ("SELECT id FROM people WHERE full_name NOT IN ('Ivan Petrov')", Reason.PII_OPERATION),
    ("SELECT id FROM people WHERE full_name <> 'Ivan Petrov'", Reason.PII_OPERATION),
    ("SELECT id FROM people WHERE full_name > 'A'", Reason.PII_OPERATION),
    ("SELECT id FROM people WHERE full_name BETWEEN 'A' AND 'B'", Reason.PII_OPERATION),
    ("SELECT id FROM people WHERE full_name IS NULL", Reason.PII_OPERATION),
    ("SELECT id FROM people WHERE full_name = city", Reason.PII_JOIN_WITH_OPEN),
    ("SELECT id FROM people WHERE full_name = lower('X')", Reason.PII_OPERATION),
    ("SELECT id FROM people WHERE full_name = NULL", Reason.PII_OPERATION),
    ("SELECT full_name = 'Ivan Petrov' FROM people", Reason.PII_OPERATION),
    ("SELECT id FROM people WHERE (full_name = 'Ivan Petrov') = (1 = 1)", Reason.PII_OPERATION),
    (
        "SELECT id FROM people WHERE full_name = 'Ivan Petrov' OR full_name = 'Anna Sidorova'",
        ([], 2, 0),
    ),
    ("SELECT id FROM people WHERE full_name IN ('Ivan Petrov', 'Anna Sidorova')", ([], 2, 0)),
    ("SELECT id FROM people WHERE phone = 5550101", ([], 1, 0)),
    ("SELECT id FROM people WHERE full_name = 5", Reason.LITERAL_TYPE_MISMATCH),
    ("SELECT id FROM people WHERE phone = -5", Reason.PII_OPERATION),
    # IN with a subquery
    ("SELECT id FROM people WHERE full_name IN (SELECT customer_name FROM orders)", OK),
    (
        "SELECT id FROM people WHERE full_name IN (SELECT note FROM orders)",
        Reason.PII_JOIN_WITH_OPEN,
    ),
    (
        "SELECT id FROM people WHERE id IN (SELECT customer_name FROM orders)",
        Reason.PII_JOIN_WITH_OPEN,
    ),
    (
        "SELECT id FROM people WHERE full_name IN (SELECT count(*) FROM orders)",
        Reason.PII_JOIN_WITH_OPEN,
    ),
    ("SELECT id FROM people WHERE id IN (SELECT id FROM orders)", OK),
    # tokens and literals
    (f"SELECT id FROM people WHERE full_name = '{TK}'", ([], 0, 1)),  # noqa: S608
    (f"SELECT id FROM people WHERE phone = '{TK}'", ([], 0, 1)),  # noqa: S608
    (f"SELECT id FROM orders WHERE note = '{TK}'", OK),  # noqa: S608
    (f"SELECT id FROM people WHERE full_name IN ('{TK}', 'Ivan Petrov')", ([], 1, 1)),  # noqa: S608
    ("SELECT id FROM people WHERE full_name = 'tk_SHORT'", ([], 1, 0)),
    # CASE and aggregates
    # SUM / AVG take a bare column or a CASE of small integers (R33); COUNT keeps the CASE form
    ("SELECT sum(CASE WHEN full_name = 'Ivan Petrov' THEN 1 END) FROM people", ([], 1, 0)),
    ("SELECT sum(CASE WHEN id = 1 THEN phone END) FROM people", NNA),
    ("SELECT count(CASE WHEN full_name = 'Ivan Petrov' THEN 1 END) FROM people", ([], 1, 0)),
    ("SELECT CASE WHEN id = 1 THEN full_name END FROM people", Reason.PII_OPERATION),
    ("SELECT coalesce(full_name, 'x') FROM people", Reason.PII_OPERATION),
    ("SELECT count(*) FROM people", OK),
    ("SELECT count(DISTINCT full_name) FROM people", OK),
    ("SELECT count(full_name) FROM people", Reason.PII_OPERATION),
    ("SELECT sum(DISTINCT phone) FROM people", Reason.PII_OPERATION),
    ("SELECT max(phone) FROM people", Reason.PII_OPERATION),
    ("SELECT count(notes) FROM people", Reason.HIDDEN_COLUMN),
    ("SELECT DISTINCT full_name, city FROM people", ([0], 0, 0)),
    ("SELECT city FROM people GROUP BY upper(full_name), city", Reason.PII_OPERATION),
    # HAVING
    (
        "SELECT full_name FROM people GROUP BY full_name HAVING full_name = 'Ivan Petrov'",
        ([0], 1, 0),
    ),
    ("SELECT city FROM people GROUP BY city HAVING count(DISTINCT full_name) > 1", OK),
    (
        "SELECT full_name FROM people GROUP BY full_name HAVING full_name <> 'x'",
        Reason.PII_OPERATION,
    ),
    ("SELECT city FROM people GROUP BY city HAVING min(full_name) = 'x'", Reason.PII_OPERATION),
    # ORDER BY
    ("SELECT id FROM people ORDER BY full_name", Reason.PII_OPERATION),
    ("SELECT id, full_name FROM people ORDER BY 2", Reason.PII_OPERATION),
    ("SELECT id, full_name FROM people ORDER BY 1", ([1], 0, 0)),
    ("SELECT full_name AS n FROM people ORDER BY upper(n)", Reason.NODE_NOT_ALLOWED),
    ("SELECT id AS city FROM people ORDER BY city", Reason.AMBIGUOUS_COLUMN),  # alias shadows
    ("SELECT id AS n FROM people ORDER BY n", OK),
    # UNION
    ("SELECT full_name FROM people UNION SELECT customer_name FROM orders", ([0], 0, 0)),
    ("SELECT full_name FROM people UNION SELECT note FROM orders", Reason.PII_JOIN_WITH_OPEN),
    ("SELECT note FROM orders UNION ALL SELECT full_name FROM people", Reason.PII_JOIN_WITH_OPEN),
    ("SELECT full_name FROM people UNION SELECT NULL", ([0], 0, 0)),
    (
        "SELECT id, full_name FROM people UNION SELECT id, note FROM orders",
        Reason.PII_JOIN_WITH_OPEN,
    ),
    ("SELECT full_name FROM people UNION SELECT 'Ivan Petrov'", Reason.PII_JOIN_WITH_OPEN),
    (
        "SELECT full_name FROM people UNION SELECT customer_name FROM orders ORDER BY 1",
        Reason.PII_OPERATION,
    ),
    ("SELECT id FROM people UNION SELECT id FROM orders ORDER BY 1", OK),
    ("SELECT * FROM people UNION SELECT * FROM people", Reason.UNKNOWN_COLUMN),
    # scalar subquery output
    ("SELECT (SELECT o.customer_name FROM orders o WHERE o.id = p.id) FROM people p", ([0], 0, 0)),
    ("SELECT (SELECT max(customer_name) FROM orders) FROM people", Reason.PII_OPERATION),
    ("SELECT id FROM people WHERE full_name = (SELECT customer_name FROM orders LIMIT 1)", OK),
    (
        "SELECT id FROM people WHERE city = (SELECT customer_name FROM orders LIMIT 1)",
        Reason.PII_JOIN_WITH_OPEN,
    ),
    (
        "SELECT id FROM people WHERE full_name = (SELECT note FROM orders LIMIT 1)",
        Reason.PII_OPERATION,
    ),
    ("SELECT upper((SELECT customer_name FROM orders LIMIT 1)) FROM people", Reason.PII_OPERATION),
    ("SELECT (SELECT * FROM orders LIMIT 1) FROM people", Reason.UNKNOWN_COLUMN),
    (
        (
            "SELECT id FROM people p WHERE EXISTS "
            "(SELECT 1 FROM orders o WHERE o.customer_name = p.full_name)"
        ),
        OK,
    ),
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "expected"), CASES)
def test_ruling(policy: PolicyRun, dialect: str, sql: str, expected: Outcome) -> None:
    assert summary(policy(sql, dialect)) == expected


def test_placeholder_only_on_recheck(policy: PolicyRun) -> None:
    sql = "SELECT id FROM people WHERE full_name = ? OR phone IN (?, 5550101)"
    assert summary(policy(sql, "sqlite", placeholders=True)) == ([], 1, 0)
    assert policy(sql, "sqlite") == Reason.NODE_NOT_ALLOWED
    assert policy(sql, "sqlite", nodes=False) == Reason.PII_OPERATION


def test_only_a_cast_bind_counts_as_a_placeholder(policy: PolicyRun) -> None:
    sql = "SELECT id FROM people WHERE full_name = CAST(id AS TEXT)"
    assert policy(sql, "sqlite", placeholders=True) == Reason.PII_OPERATION
