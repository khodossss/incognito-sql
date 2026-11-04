"""Review probes: shadowed names, ORDER BY names and ordinals, stars over derived sources."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import DIALECTS, Outcome, PolicyRun, summary

AMB = Reason.AMBIGUOUS_COLUMN
OP = Reason.PII_OPERATION
OK: Outcome = ([], 0, 0)
NNA = Reason.NODE_NOT_ALLOWED

# (sql, full chain, policy alone past qualify_tree's shadowing checks)
SHADOWED: list[tuple[str, Outcome, Outcome]] = [
    # a CTE name hides the correlated outer alias
    (
        (
            "WITH p AS (SELECT city AS full_name FROM people) "
            "SELECT (SELECT upper(p.full_name)) FROM people AS p"
        ),
        AMB,
        OP,
    ),
    (
        (
            "WITH p AS (SELECT city AS full_name FROM people) "
            "SELECT (SELECT 1 WHERE p.full_name LIKE 'I%') FROM people AS p"
        ),
        AMB,
        OP,
    ),
    (
        (
            "WITH o AS (SELECT note AS customer_name FROM orders) "
            "SELECT (SELECT 1 WHERE upper(o.customer_name) = 'X') FROM orders AS o"
        ),
        AMB,
        OP,
    ),
    (
        (
            "WITH o AS (SELECT note AS customer_name, note FROM orders) "
            "SELECT (SELECT 1 WHERE o.customer_name = o.note) FROM orders AS o"
        ),
        AMB,
        Reason.PII_JOIN_WITH_OPEN,
    ),
    (
        (
            "SELECT (WITH p AS (SELECT city AS full_name FROM people) "
            "SELECT upper(p.full_name)) FROM people AS p"
        ),
        AMB,
        OP,
    ),
    # an expression as sort key is closed (R27), before and past the shadowing checks
    ("SELECT city AS full_name FROM people ORDER BY upper(full_name)", NNA, NNA),
    (
        "SELECT id, id AS full_name FROM people ORDER BY substring(full_name, 1, 1) = 'A' DESC, id",
        NNA,
        NNA,
    ),
    (
        (
            "SELECT id FROM people WHERE id IN "
            "(SELECT id AS full_name FROM people ORDER BY upper(full_name) LIMIT 1)"
        ),
        NNA,
        NNA,
    ),
    (
        (
            "WITH c AS (SELECT id AS full_name FROM people ORDER BY upper(full_name) LIMIT 1) "
            "SELECT c.full_name FROM c"
        ),
        NNA,
        NNA,
    ),
    ("SELECT DISTINCT city AS full_name FROM people ORDER BY upper(full_name)", NNA, NNA),
    ("SELECT id AS phone FROM people ORDER BY phone + 0", NNA, NNA),
    ("SELECT id AS full_name FROM people ORDER BY full_name", AMB, OP),
    ("SELECT id AS full_name FROM people ORDER BY (full_name) DESC", AMB, OP),
    # HAVING alias rewrite: sqlglot reads the alias, the database the column (R26 only)
    (
        "SELECT city AS full_name FROM people GROUP BY city HAVING full_name LIKE 'I%'",
        AMB,
        ([], 0, 0),
    ),
]

CASES: list[tuple[str, Outcome]] = [
    # R26 (a): an alias equal to a source column name
    ("SELECT count(*) AS id FROM people", AMB),
    ("SELECT o.customer_name AS full_name FROM orders o", ([0], 0, 0)),
    ("SELECT o.customer_name AS full_name FROM orders o JOIN people p ON p.id = o.id", AMB),
    ("SELECT full_name AS full_name FROM people", ([0], 0, 0)),
    ("SELECT p.id, o.id FROM people p JOIN orders o ON o.customer_name = p.full_name", OK),
    # R26 (b): a CTE name equal to a table name or a table alias
    ("WITH people AS (SELECT id FROM orders) SELECT id FROM people", AMB),
    ("WITH c AS (SELECT id FROM orders) SELECT c.id FROM people AS c", AMB),
    (
        (
            "WITH c AS (SELECT id FROM orders) "
            "SELECT x.id FROM people x WHERE x.id IN (SELECT c.id FROM c)"
        ),
        OK,
    ),
    # R26 (c): duplicate CTE names or table aliases
    ("WITH c AS (SELECT id FROM orders), C AS (SELECT id FROM people) SELECT id FROM c", AMB),
    ("SELECT p.id FROM people p WHERE EXISTS (SELECT 1 FROM orders p)", AMB),
    # R3: stars only over base tables
    ("SELECT * FROM (SELECT full_name FROM people) d", Reason.NODE_NOT_ALLOWED),
    ("WITH c AS (SELECT full_name FROM people) SELECT * FROM c", Reason.NODE_NOT_ALLOWED),
    ("SELECT d.* FROM (SELECT full_name FROM people) d", Reason.NODE_NOT_ALLOWED),
    ("SELECT p.* FROM people p JOIN (SELECT id FROM orders) d ON d.id = p.id", OK),
    (
        "SELECT * FROM people p JOIN (SELECT id FROM orders) d ON d.id = p.id",
        Reason.NODE_NOT_ALLOWED,
    ),
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "chain", "alone"), SHADOWED)
def test_shadowed_names(
    policy: PolicyRun, dialect: str, sql: str, chain: Outcome, alone: Outcome
) -> None:
    assert summary(policy(sql, dialect)) == chain
    assert summary(policy(sql, dialect, nodes=False)) == alone


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "expected"), CASES)
def test_probe(policy: PolicyRun, dialect: str, sql: str, expected: Outcome) -> None:
    assert summary(policy(sql, dialect)) == expected
