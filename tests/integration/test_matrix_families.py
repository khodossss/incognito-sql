"""On every DBMS identifier values meet only within one type family: no cast can fail on some."""

import re

import pytest

from incognito_sql.core.pipeline import Gateway

from .conftest import Field
from .test_matrix import rows

pytestmark = pytest.mark.integration
MISMATCH = {"error": "literal_type_mismatch", "sqlstate": None}
MIXED = [
    (
        "SELECT q.x FROM (SELECT phone AS x FROM people WHERE id = 1"
        " UNION ALL SELECT full_name FROM people WHERE id = 1) q"
    ),
    (
        "SELECT id FROM people WHERE full_name IN"
        " (SELECT full_name FROM people UNION ALL SELECT phone FROM people)"
    ),
    (
        "SELECT o.id FROM orders o JOIN (SELECT full_name AS x FROM people"
        " UNION ALL SELECT phone FROM people) q ON q.x = o.customer_name"
    ),
]


@pytest.mark.parametrize("sql", MIXED)
def test_union_across_families_is_refused(field: Field, gateway: Gateway, sql: str) -> None:
    assert gateway.query(field.sql(sql), "c1") == MISMATCH


def test_union_within_one_family_works(field: Field, gateway: Gateway) -> None:
    sql = (
        "SELECT q.x FROM (SELECT full_name AS x FROM people WHERE id = 1"
        " UNION ALL SELECT customer_name FROM orders WHERE id = 10) q"
    )
    assert len(rows(gateway.query(field.sql(sql), "c1"))) == 2


# Reviewer probes: each pair fails a cast for some values only.
WIDE_PROBES = {
    "tsql": [
        "SELECT num FROM wide UNION ALL SELECT m FROM wide",
        "SELECT id FROM wide WHERE num = m",
        "SELECT i FROM wide UNION ALL SELECT sm FROM wide",
        "SELECT id FROM wide WHERE i = sm",
    ],
    "duckdb": [
        "SELECT id FROM wide WHERE h = d",
        "SELECT h FROM wide UNION ALL SELECT d FROM wide",
        "SELECT id FROM wide WHERE uh = b",
        "SELECT uh FROM wide UNION ALL SELECT b FROM wide",
    ],
}


def test_wide_numeric_identifiers_are_not_cast(field: Field, gateway: Gateway) -> None:
    probes = WIDE_PROBES.get(field.backend.dialect)
    if probes is None:
        pytest.skip("no wide numeric types in this world")
    for sql in probes:
        assert gateway.query(sql, "c1") == MISMATCH, sql
    same = "SELECT id FROM wide WHERE num = i" if field.backend.dialect == "tsql" else None
    if same is not None:  # BIGINT against INT: one group
        assert rows(gateway.query(same, "c1")) == []


def test_money_token_follow_up(field: Field, gateway: Gateway) -> None:
    if field.backend.dialect != "postgres":
        pytest.skip("MONEY identifier only in the Postgres world")
    first = gateway.query("SELECT id, m FROM wallets WHERE id = 1", "c1")
    [[pk, link]] = rows(first)
    found = re.search(r"tk_[a-z2-7]{16}", str(link))
    assert pk == 1
    assert found is not None
    again = gateway.query(f"SELECT id FROM wallets WHERE m = '{found.group(0)}'", "c1")  # noqa: S608
    assert rows(again) == [[1]]
    assert gateway.query("SELECT id FROM wallets WHERE m = 5", "c1") == MISMATCH
