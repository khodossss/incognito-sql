"""Row limits are integer literals only; identifiers are compared within one type family."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import PolicyRun, summary

ALL = ["postgres", "sqlite", "mysql", "duckdb", "tsql"]
REFUSED = [
    ("tsql", "SELECT TOP (SELECT phone FROM people WHERE id = 1) id FROM orders"),
    ("tsql", "SELECT TOP (SELECT COUNT(*) FROM people) id FROM orders"),
    ("tsql", "SELECT id FROM orders ORDER BY id OFFSET (SELECT 1) ROWS"),
    ("tsql", "SELECT id FROM orders ORDER BY id OFFSET 0 ROWS FETCH NEXT 2 ROWS ONLY"),
    *[
        (d, sql)
        for d in ["postgres", "sqlite", "mysql", "duckdb"]
        for sql in [
            "SELECT id FROM orders LIMIT (SELECT phone FROM people WHERE id = 1)",
            "SELECT id FROM orders LIMIT (SELECT COUNT(*) FROM people)",
            "SELECT id FROM orders LIMIT 1 OFFSET (SELECT 1)",
            "SELECT id FROM orders LIMIT 1+1",
        ]
    ],
    ("postgres", "SELECT id FROM orders LIMIT ALL"),
    ("sqlite", "SELECT id FROM orders LIMIT -1 OFFSET 1"),
    ("postgres", "SELECT id FROM orders FETCH FIRST 2 ROWS ONLY"),
    ("postgres", "SELECT n.id FROM (SELECT id FROM orders LIMIT (SELECT 2)) AS n"),
]
KEPT = [
    ("tsql", "SELECT TOP 5 id FROM orders"),
    ("tsql", "SELECT TOP (5) id FROM orders"),
    ("tsql", "SELECT id FROM orders ORDER BY id OFFSET 2 ROWS"),
    ("mysql", "SELECT id FROM orders LIMIT 2, 3"),
    *[(d, "SELECT id FROM orders LIMIT 5 OFFSET 1") for d in ["postgres", "sqlite", "duckdb"]],
    ("postgres", "SELECT id FROM orders LIMIT (5)"),
]


@pytest.mark.parametrize(("dialect", "sql"), REFUSED)
def test_computed_row_limit_is_refused(policy: PolicyRun, dialect: str, sql: str) -> None:
    assert policy(sql, dialect) is Reason.NODE_NOT_ALLOWED


@pytest.mark.parametrize(("dialect", "sql"), KEPT)
def test_integer_row_limit_passes(policy: PolicyRun, dialect: str, sql: str) -> None:
    assert summary(policy(sql, dialect)) == ([], 0, 0)


@pytest.mark.parametrize("dialect", ALL)
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM people p WHERE p.phone = p.full_name",
        "SELECT id FROM people p WHERE p.full_name IN (p.phone)",
        "SELECT o.id FROM orders o JOIN people p ON p.phone = o.customer_name",
        "SELECT id FROM people WHERE phone IN (SELECT customer_name FROM orders)",
    ],
)
def test_identifiers_of_two_families_are_not_compared(
    policy: PolicyRun, dialect: str, sql: str
) -> None:
    assert policy(sql, dialect) is Reason.LITERAL_TYPE_MISMATCH


@pytest.mark.parametrize("dialect", ALL)
def test_identifiers_of_one_family_are_compared(policy: PolicyRun, dialect: str) -> None:
    sql = "SELECT o.id FROM orders o JOIN people p ON p.full_name = o.customer_name"
    assert summary(policy(sql, dialect)) == ([], 0, 0)
