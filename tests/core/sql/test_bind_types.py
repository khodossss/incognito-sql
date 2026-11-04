"""A bind compared with a wide, exact or time-zone identifier is cast to the column's exact type."""

from pathlib import Path

import pytest
from sqlglot import exp

from incognito_sql.core.config import ColumnClass, Declaration, Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.allowlist import check_nodes
from incognito_sql.core.sql.bind_type import bind_cast
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.policy import enforce
from incognito_sql.core.sql.resolve import qualify_tree
from incognito_sql.core.sql.rewrite import prepare
from incognito_sql.core.tokens.store import TokenStore

from .conftest import NOW
from .reflected import reflected_types


@pytest.mark.parametrize(
    ("dialect", "column_type", "target"),
    [
        ("duckdb", "UHUGEINT", "UINT128"),
        ("duckdb", "HUGEINT", "INT128"),
        ("duckdb", "UBIGINT", "UBIGINT"),
        ("duckdb", "DECIMAL(10,2)", "DECIMAL(10, 2)"),
        ("duckdb", "TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ"),
        ("duckdb", "TIMESTAMP", "TIMESTAMP"),
        ("postgres", "MONEY", "MONEY"),
        ("postgres", "TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ"),
        ("postgres", "NUMERIC(10, 2)", "DECIMAL(10, 2)"),
        ("mysql", "BIGINT UNSIGNED", "UNSIGNED"),
        ("mysql", "DECIMAL(10, 2)", "DECIMAL(10, 2)"),
        ("mysql", "DATETIME(3)", "DATETIME(3)"),
        ("tsql", "MONEY", "MONEY"),
        ("tsql", "REAL", "FLOAT(24)"),
        ("tsql", "DATETIMEOFFSET", "DATETIMEOFFSET"),
    ],
)
def test_bind_is_cast_to_the_exact_type(dialect: str, column_type: str, target: str) -> None:
    found = bind_cast(column_type, dialect)
    assert found is not None
    cast = exp.Cast(this=exp.column("x"), to=found).sql(dialect=dialect)
    assert cast == f"CAST(x AS {target})"


@pytest.mark.parametrize(
    ("dialect", "column_type"),
    [
        ("postgres", "BIGINT"),
        ("duckdb", "INTEGER"),
        ("tsql", 'NVARCHAR(10) COLLATE "SQL_LATIN1_GENERAL_CP1_CI_AS"'),
        ("sqlite", "DECIMAL(10, 2)"),  # SQLite converts the bind by the column's affinity
        ("sqlite", "DATE"),
    ],
)
def test_no_cast_where_none_is_needed(dialect: str, column_type: str) -> None:
    assert bind_cast(column_type, dialect) is None


@pytest.mark.parametrize(
    ("dialect", "column_type"),
    [
        ("mysql", "INT UNSIGNED"),  # MySQL's CAST has only UNSIGNED (BIGINT)
        ("mysql", "TIMESTAMP"),
        ("duckdb", "DECIMAL(10,2)[]"),
        ("postgres", "NULL"),
        ("postgres", ""),
        ("postgres", "TSVECTOR"),
        ("mysql", "DECIMAL(10, 2) UNSIGNED"),  # MySQL's CAST has no UNSIGNED decimal
        ("mysql", "DOUBLE UNSIGNED"),
        ("mysql", "FLOAT UNSIGNED"),  # MySQL's CAST has no UNSIGNED float either
        ("mysql", "FLOAT(10) UNSIGNED"),
        ("mysql", "REAL UNSIGNED"),
        ("duckdb", "ENUM('calm', 'busy')"),  # enumerated, set and domain types: never cast
        ("postgres", "ENUM"),
        ("mysql", "SET"),
        ("postgres", "DOMAIN"),
        ("sqlite", "ENUM"),
    ],
)
def test_types_a_dialect_cannot_write_refuse_the_bind(dialect: str, column_type: str) -> None:
    with pytest.raises(Rejection) as raised:
        bind_cast(column_type, dialect)
    assert raised.value.reason is Reason.LITERAL_TYPE_MISMATCH


def _prepare(sql: str, store: TokenStore, folder: Path) -> str:
    types = reflected_types(folder)
    catalog = Catalog(columns={"w": types})
    decl = Declaration(
        dsn_env="X",
        dialect="duckdb",
        columns={"w": dict.fromkeys(types, ColumnClass.IDENTIFIER)},
        entities=[],
    )
    tree = parse(sql, "duckdb", Limits())
    check_nodes(tree)
    qualified = qualify_tree(tree, catalog, "duckdb")
    return prepare(qualified, enforce(qualified, catalog, decl), store, catalog, decl, NOW).sql


def test_rewrite_casts_the_bind_and_passes_the_recheck(store: TokenStore, tmp_path: Path) -> None:
    sql = _prepare("SELECT big FROM w WHERE uhuge IN (5, 7) AND big = 5", store, tmp_path)
    assert "w.uhuge IN (CAST(:p0 AS UINT128), CAST(:p1 AS UINT128))" in sql
    assert "w.big IN (:p0)" in sql
    stamped = _prepare("SELECT big FROM w WHERE dec = 5.12", store, tmp_path)
    assert "w.dec IN (CAST(:p0 AS DECIMAL(10, 2)))" in stamped


@pytest.mark.parametrize(
    "sql",
    ["SELECT big FROM w WHERE dec = 5.123", "SELECT big FROM w WHERE ubig = 18446744073709551616"],
)
def test_literals_the_type_cannot_hold_are_refused(
    sql: str, store: TokenStore, tmp_path: Path
) -> None:
    with pytest.raises(Rejection) as raised:
        _prepare(sql, store, tmp_path)
    assert raised.value.reason is Reason.LITERAL_TYPE_MISMATCH


def test_token_without_a_form_the_type_holds_compares_false(
    store: TokenStore, tmp_path: Path
) -> None:
    tok = store.tokenize("-5", NOW)
    both = f"SELECT big FROM w WHERE ubig = '{tok}' OR big = '{tok}'"  # noqa: S608
    sql = _prepare(both, store, tmp_path)
    assert "WHERE :p0 = :p1 OR w.big IN (:p2)" in sql
    listed = _prepare(f"SELECT big FROM w WHERE ubig IN ('{tok}', 7)", store, tmp_path)  # noqa: S608
    assert "w.ubig IN (CAST(:p0 AS UBIGINT))" in listed
