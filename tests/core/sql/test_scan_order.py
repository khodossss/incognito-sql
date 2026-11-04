"""Strict closes what the scan order decides; balanced and permissive answer the same SQL."""

import pytest

from incognito_sql.core.errors import Reason
from incognito_sql.core.sql.catalog import Catalog

from .conftest import CATALOG, DECL, DIALECTS, PolicyRun

BALANCED = DECL.model_copy(update={"protection": "balanced"})


def _passes(outcome: object) -> bool:
    return not isinstance(outcome, Reason)


@pytest.mark.parametrize("column_type", ["REAL", "DOUBLE PRECISION", "FLOAT8", "FLOATING"])
@pytest.mark.parametrize("dialect", DIALECTS)
def test_a_float_sum_is_refused(policy: PolicyRun, column_type: str, dialect: str) -> None:
    catalog = Catalog(
        columns={**CATALOG.columns, "orders": {**CATALOG.columns["orders"], "amount": column_type}}
    )
    sql = "SELECT SUM(amount), AVG(amount) FROM orders"
    assert policy(sql, dialect, catalog=catalog) == Reason.FLOAT_AGGREGATE
    assert _passes(policy(sql, dialect, decl=BALANCED, catalog=catalog))
    assert _passes(policy(sql, dialect))  # NUMERIC


@pytest.mark.parametrize("dialect", DIALECTS)
def test_an_integer_sum_is_exact(policy: PolicyRun, dialect: str) -> None:
    decl = DECL.model_copy(update={"dialect": dialect})
    assert _passes(policy("SELECT SUM(id), AVG(id) FROM orders", dialect, decl=decl))


FALLIBLE = [
    "SELECT id FROM people p WHERE EXISTS (SELECT 1 FROM orders o WHERE o.id + 1 > 2)",
    "SELECT id FROM people p WHERE p.id IN (SELECT o.id / 2 FROM orders o)",
    "SELECT (SELECT o.id - 1 FROM orders o WHERE o.id = p.id) FROM people p",
    "WITH c AS (SELECT o.id * 2 AS x FROM orders o) SELECT x FROM c",
    (
        "SELECT id FROM people p WHERE EXISTS"
        " (SELECT 1 FROM orders o WHERE CASE WHEN o.id = 3 THEN 1 / 0 ELSE 0 END = 0)"
    ),
]
WHOLE = [
    "SELECT id FROM people p WHERE p.id + 1 > 2",
    "SELECT id FROM people p WHERE EXISTS (SELECT COUNT(*) FROM orders o WHERE o.id + 1 > 2)",
    "SELECT id FROM people p WHERE EXISTS (SELECT 1 FROM orders o WHERE o.id = 1 + 1)",
    "SELECT d.x FROM (SELECT o.id * 2 AS x FROM orders o) AS d",
    "SELECT (SELECT max(o.id + p.id) FROM orders o) FROM people p",
    (
        "SELECT id FROM people p WHERE EXISTS"
        " (SELECT 1 FROM orders o WHERE o.id > -1 AND o.customer_name = p.full_name)"
    ),
]
NESTED = (
    "SELECT id FROM people p WHERE EXISTS (SELECT 1 FROM orders o"
    " WHERE (SELECT COUNT(*) FROM orders o2 WHERE o2.id / (o.id - 3) > 0) > 0)"
)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("sql", FALLIBLE)
def test_an_error_where_a_subquery_may_stop_early_is_refused(
    policy: PolicyRun, sql: str, dialect: str
) -> None:
    assert policy(sql, dialect) == Reason.FALLIBLE_SUBQUERY
    assert _passes(policy(sql, dialect, decl=BALANCED))


@pytest.mark.parametrize("dialect", DIALECTS)
def test_an_aggregate_read_row_by_row_from_outside_may_stop_early(
    policy: PolicyRun, dialect: str
) -> None:
    assert policy(NESTED, dialect) == Reason.FALLIBLE_SUBQUERY


CONVERTED = [
    "SELECT id FROM people p WHERE EXISTS (SELECT 1 FROM orders o WHERE o.note = 5)",
    "SELECT id FROM people p WHERE p.id IN (SELECT o.id FROM orders o WHERE o.note > 5)",
    (
        "SELECT id FROM people p WHERE EXISTS"
        " (SELECT 1 FROM orders o WHERE CASE WHEN o.id = 1 THEN o.note ELSE 1 END = 1)"
    ),
    "SELECT id FROM people p WHERE EXISTS (SELECT 1 FROM orders o WHERE o.note = -5)",
    "SELECT id FROM people p WHERE EXISTS (SELECT 1 FROM orders o WHERE o.note = (SELECT 5))",
    (
        "SELECT id FROM people p WHERE EXISTS"
        " (SELECT 1 FROM orders o WHERE o.note IN (SELECT o2.id FROM orders o2))"
    ),
    (
        "SELECT id FROM people p WHERE EXISTS"
        " (SELECT 1 FROM orders o WHERE CASE WHEN o.id = 1 THEN o.note ELSE -1 END = 1)"
    ),
]
TEXT_ONLY = [
    "SELECT id FROM people p WHERE EXISTS (SELECT 1 FROM orders o WHERE o.note = 'x')",
    "SELECT id FROM people p WHERE EXISTS (SELECT 1 FROM orders o WHERE o.note = lower(o.note))",
    (
        "SELECT id FROM people p WHERE EXISTS"
        " (SELECT 1 FROM orders o WHERE o.note IN (SELECT o2.note FROM orders o2))"
    ),
]


@pytest.mark.parametrize("dialect", ["tsql", "duckdb"])
@pytest.mark.parametrize("sql", CONVERTED)
def test_an_implicit_conversion_where_a_subquery_may_stop_early_is_refused(
    policy: PolicyRun, sql: str, dialect: str
) -> None:
    decl = DECL.model_copy(update={"dialect": dialect})
    assert policy(sql, dialect, decl=decl) == Reason.FALLIBLE_SUBQUERY
    assert _passes(policy(sql, dialect, decl=BALANCED.model_copy(update={"dialect": dialect})))


@pytest.mark.parametrize("dialect", ["tsql", "duckdb"])
@pytest.mark.parametrize("sql", TEXT_ONLY)
def test_text_met_with_text_converts_nothing(policy: PolicyRun, sql: str, dialect: str) -> None:
    assert _passes(policy(sql, dialect, decl=DECL.model_copy(update={"dialect": dialect})))


def test_a_boolean_converts_text_on_duckdb(policy: PolicyRun) -> None:
    sql = "SELECT id FROM people p WHERE EXISTS (SELECT 1 FROM orders o WHERE o.note = TRUE)"
    duckdb = DECL.model_copy(update={"dialect": "duckdb"})
    assert policy(sql, "duckdb", decl=duckdb) == Reason.FALLIBLE_SUBQUERY


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("sql", WHOLE)
def test_an_error_over_every_row_read_is_not(policy: PolicyRun, sql: str, dialect: str) -> None:
    assert _passes(policy(sql, dialect))


SPELLINGS = [
    "SELECT DISTINCT o.note FROM orders o",
    "SELECT o.note, COUNT(*) FROM orders o GROUP BY o.note",
    "SELECT MIN(o.note) FROM orders o",
    "SELECT DISTINCT lower(o.note) FROM orders o",
    "SELECT o.note FROM orders o UNION SELECT o.note FROM orders o",
    (
        "SELECT DISTINCT d.note FROM"
        " (SELECT o.note FROM orders o JOIN people p ON customer_name = full_name) AS d"
    ),
]
ONE_SPELLING = [
    "SELECT o.note FROM orders o UNION ALL SELECT o.note FROM orders o",
    "SELECT DISTINCT o.id FROM orders o",
    "SELECT o.note FROM orders o",
]


@pytest.mark.parametrize("dialect", ["mysql", "tsql"])
@pytest.mark.parametrize("sql", SPELLINGS)
def test_a_case_blind_collation_picks_a_spelling_in_scan_order(
    policy: PolicyRun, sql: str, dialect: str
) -> None:
    decl = DECL.model_copy(update={"dialect": dialect})
    assert policy(sql, dialect, decl=decl) == Reason.EQUAL_SPELLINGS
    assert _passes(policy(sql, dialect, decl=BALANCED.model_copy(update={"dialect": dialect})))
    assert _passes(policy(sql, "postgres"))  # a binary collation keeps spellings apart


@pytest.mark.parametrize("sql", ONE_SPELLING)
def test_no_choice_among_spellings_answers(policy: PolicyRun, sql: str) -> None:
    mysql = DECL.model_copy(update={"dialect": "mysql"})
    assert _passes(policy(sql, "mysql", decl=mysql))
