"""Values compared with wide, exact or time-zone identifiers: the bind takes the column's type."""

import pytest

from incognito_sql.core.db import make_engine
from incognito_sql.core.pipeline import Gateway
from incognito_sql.core.sql.catalog import reflect

from .conftest import Field
from .test_matrix import rows, token
from .test_matrix_families import MISMATCH

pytestmark = pytest.mark.integration
# Row 1 holds a value past BIGINT (or the type's edge); row 2 holds 5.
LITERALS = {"duckdb": ["uh", "h", "ub", "d"], "mysql": ["ub"]}
TOKENS = {
    "postgres": [("wallets", "m"), ("moments", "tz")],
    "mysql": [("wide", "ub")],
    "duckdb": [("wide", "uh"), ("wide", "h"), ("wide", "ub"), ("wide", "d"), ("moments", "tz")],
    "tsql": [("wide", "m"), ("wide", "sm")],
}
REFUSED = {
    "duckdb": [
        "SELECT id FROM wide WHERE d = 5.123",
        "SELECT id FROM wide WHERE ub = 18446744073709551616",
    ],
    "mysql": [
        "SELECT id FROM wide WHERE ui = 5",  # MySQL CAST has no INT UNSIGNED
        "SELECT id FROM wide WHERE ub = b",
        "SELECT ub FROM wide UNION ALL SELECT b FROM wide",
    ],
}
NAIVE_AND_AWARE = [
    "SELECT id FROM moments WHERE ts = tz",
    "SELECT id FROM moments WHERE ts IN (SELECT tz FROM moments)",
    "SELECT ts FROM moments UNION ALL SELECT tz FROM moments",
]
REFLECTED = {
    "postgres": {("moments", "ts"): "TIMESTAMP", ("moments", "tz"): "TIMESTAMP WITH TIME ZONE"},
    "mysql": {("wide", "ub"): "BIGINT UNSIGNED", ("wide", "b"): "BIGINT"},
    "duckdb": {("moments", "ts"): "TIMESTAMP", ("moments", "tz"): "TIMESTAMP WITH TIME ZONE"},
}


def _cases[T](table: dict[str, list[T]], field: Field) -> list[T]:
    found = table.get(field.backend.dialect)
    if found is None:
        pytest.skip("no such column in this world")
    return found


def test_literals_never_make_the_column_cast(field: Field, gateway: Gateway) -> None:
    for column in _cases(LITERALS, field):
        for sql in (f"{column} = 5", f"{column} IN (5, 7)", f"{column} = 5 AND id = 2"):
            assert rows(gateway.query(f"SELECT id FROM wide WHERE {sql}", "c1")) == [[2]], sql  # noqa: S608
        assert rows(gateway.query(f"SELECT id FROM wide WHERE id = 1 AND {column} = 5", "c1")) == []  # noqa: S608


def test_token_follow_up_on_typed_columns(field: Field, gateway: Gateway) -> None:
    for table, column in _cases(TOKENS, field):
        first = gateway.query(f"SELECT id, {column} FROM {table} WHERE id = 1", "c1")  # noqa: S608
        [[pk, link]] = rows(first)
        assert pk == 1
        again = gateway.query(f"SELECT id FROM {table} WHERE {column} = '{token(link)}'", "c1")  # noqa: S608
        assert rows(again) == [[1]], (table, column)


def test_values_the_type_cannot_hold_are_refused(field: Field, gateway: Gateway) -> None:
    for sql in _cases(REFUSED, field):
        assert gateway.query(sql, "c1") == MISMATCH, sql


def test_naive_and_aware_timestamps_never_meet(field: Field, gateway: Gateway) -> None:
    if field.backend.dialect not in {"postgres", "duckdb"}:
        pytest.skip("no time-zone columns in this world")
    for sql in NAIVE_AND_AWARE:
        assert gateway.query(sql, "c1") == MISMATCH, sql


def test_open_time_zone_values_are_answered(field: Field, gateway: Gateway) -> None:
    if field.backend.dialect not in {"postgres", "duckdb"}:
        pytest.skip("no time-zone columns in this world")
    assert len(rows(gateway.query("SELECT seen FROM moments", "c1"))) == 2


def test_reflection_keeps_unsigned_and_time_zone(field: Field) -> None:
    expected = REFLECTED.get(field.backend.dialect)
    if expected is None:
        pytest.skip("no such column in this world")
    engine = make_engine(field.backend.url, field.backend.dialect)
    try:
        catalog = reflect(engine, field.backend.dialect)
    finally:
        engine.dispose()
    assert {key: catalog.columns[key[0]][key[1]] for key in expected} == expected
