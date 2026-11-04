"""On every DBMS a row limit is an integer literal, so no value becomes a row count."""

import pytest

from incognito_sql.core.pipeline import Gateway

from .conftest import Field
from .test_matrix import rows

pytestmark = pytest.mark.integration
REFUSED = {"error": "node_not_allowed", "sqlstate": None}
COMPUTED = [
    "SELECT COUNT(*) FROM (SELECT id FROM orders LIMIT (SELECT phone FROM people WHERE id = 1)) q",
    "SELECT id FROM orders LIMIT (SELECT COUNT(*) FROM people)",
    "SELECT id FROM orders ORDER BY id LIMIT 5 OFFSET (SELECT id FROM people WHERE id = 1)",
    "SELECT id FROM orders LIMIT 1+1",
]
TSQL_COMPUTED = [
    "SELECT COUNT(*) FROM (SELECT TOP (SELECT phone FROM people WHERE id = 1) id FROM orders) q",
    (
        "SELECT COUNT(*) FROM (SELECT TOP"
        " (SELECT phone FROM people WHERE full_name = 'Ivan Petrov') id FROM orders) q"
    ),
    "SELECT id FROM orders ORDER BY id OFFSET (SELECT 1) ROWS",
]


@pytest.mark.parametrize("sql", COMPUTED)
def test_computed_row_limit_is_refused(field: Field, gateway: Gateway, sql: str) -> None:
    # As written (sqlglot would fold `1+1`), translated only for SQL Server's TOP.
    query = field.sql(sql) if field.backend.dialect == "tsql" else sql
    assert gateway.query(query, "c1") == REFUSED


def test_tsql_computed_top_is_refused(field: Field, gateway: Gateway) -> None:
    if field.backend.dialect != "tsql":
        pytest.skip("TOP is SQL Server syntax")
    for sql in TSQL_COMPUTED:
        assert gateway.query(sql, "c1") == REFUSED, sql


def test_integer_row_limits_still_work(field: Field, gateway: Gateway) -> None:
    assert len(rows(gateway.query(field.sql("SELECT id FROM orders LIMIT 2"), "c1"))) == 2
    if field.backend.dialect == "tsql":
        for sql in ("SELECT TOP 2 id FROM orders", "SELECT TOP (2) id FROM orders"):
            assert len(rows(gateway.query(sql, "c1"))) == 2


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM people p WHERE p.phone = p.full_name",
        "SELECT o.id FROM orders o JOIN people p ON p.phone = o.customer_name",
    ],
)
def test_identifiers_of_two_families_are_not_compared(
    field: Field, gateway: Gateway, sql: str
) -> None:
    out = gateway.query(field.sql(sql), "c1")
    assert out == {"error": "literal_type_mismatch", "sqlstate": None}


def test_identifiers_of_one_family_are_compared(field: Field, gateway: Gateway) -> None:
    sql = "SELECT o.id FROM orders o JOIN people p ON p.full_name = o.customer_name"
    found = {row[0] for row in rows(gateway.query(field.sql(sql), "c1"))}
    assert {10, 11} <= found <= {10, 11, 12}  # 12 too where the collation ignores case
