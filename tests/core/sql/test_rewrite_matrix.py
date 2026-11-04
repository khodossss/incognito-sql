"""Every query the policy accepts survives the rewrite, its re-check, and runs on SQLite."""

import re
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from incognito_sql.core.db import make_engine
from incognito_sql.core.tokens.store import TokenStore

from . import (
    test_lineage,
    test_order_keys,
    test_policy,
    test_policy_bypasses,
    test_policy_rulings,
    test_resolve,
    test_star_places,
)
from .conftest import DIALECTS, NOW, PrepareRun

TK = test_policy_rulings.TK
ALLOWED = sorted(
    {
        sql
        for cases in (
            test_policy.CASES,
            test_policy_rulings.CASES,
            test_policy_bypasses.CASES,
            test_star_places.CASES,
            test_order_keys.CASES,
            test_resolve.CASES,
            test_lineage.CASES,
        )
        for sql, expected in cases
        if isinstance(expected, tuple)
    }
    | {sql for sql, chain, _ in test_policy_bypasses.SHADOWED if isinstance(chain, tuple)}
)
ROWS = [
    "INSERT INTO people VALUES (1, 'Ivan Petrov', 5550101, 'Zqtown', 'Zz note')",
    "INSERT INTO people VALUES (2, 'Anna Sidorova', 5550102, 'Zqville', NULL)",
    "INSERT INTO orders VALUES (1, 'Ivan Petrov', 'Zq first', 12.5)",
    "INSERT INTO orders VALUES (2, 'Zq Buyer', 'Zq second', 3)",
    "INSERT INTO audit_shadow VALUES ('Zz a', 'Zz b', 'Zz c')",
]


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    path = tmp_path / "scratch.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT, phone BIGINT,"
        " city TEXT, notes TEXT)"
    )
    con.execute("CREATE TABLE orders (id INTEGER, customer_name TEXT, note TEXT, amount NUMERIC)")
    con.execute("CREATE TABLE audit_shadow (a TEXT, b TEXT, c TEXT)")
    for row in ROWS:
        con.execute(row)
    con.commit()
    con.close()
    return make_engine(f"sqlite:///{path}", "sqlite")


def test_matrix_is_not_empty() -> None:
    assert len(ALLOWED) > 50


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("sql", ALLOWED)
def test_recheck_accepts_every_allowed_query(
    store: TokenStore, prepare_sql: PrepareRun, engine: Engine, dialect: str, sql: str
) -> None:
    sql = sql.replace(TK, store.tokenize("5550101", NOW))
    p = prepare_sql(sql, dialect)
    assert "tk_" not in p.sql
    assert "--" not in p.sql
    assert "/*" not in p.sql
    assert set(re.findall(r":(p\d+)", p.sql)) == set(p.params)
    if dialect == "sqlite" and p.sql:
        with engine.connect() as con:
            con.execute(text(p.sql), p.params).fetchall()
    engine.dispose()


@pytest.mark.parametrize(
    ("sql", "rows"),
    [
        ("SELECT id FROM people WHERE full_name = 'IVAN PETROV'", [(1,)]),
        ("SELECT id FROM people WHERE (full_name) = ('IVAN PETROV')", [(1,)]),
        ("SELECT id FROM people WHERE phone = 5550102", [(2,)]),
        ("SELECT count(*) FROM orders WHERE amount = 12.5 AND note = 'Zq first'", [(1,)]),
        ("SELECT full_name FROM people UNION SELECT customer_name FROM orders", None),
        ("SELECT * FROM people WHERE id = 1", [(1, "Ivan Petrov", 5550101, "Zqtown")]),
        ("SELECT id FROM people WHERE id IN (SELECT id FROM people WHERE id = 2)", [(2,)]),
        ("WITH c AS (SELECT * FROM people) SELECT c.city FROM c WHERE c.id = 2", [("Zqville",)]),
    ],
)
def test_binds_work_end_to_end(
    store: TokenStore,
    prepare_sql: PrepareRun,
    engine: Engine,
    sql: str,
    rows: list[tuple[object, ...]] | None,
) -> None:
    store.tokenize("Ivan Petrov", NOW)
    p = prepare_sql(sql, "sqlite")
    with engine.connect() as con:
        got = [tuple(r) for r in con.execute(text(p.sql), p.params)]
    engine.dispose()
    if rows is None:
        assert sorted(map(str, got)) == sorted(
            map(str, [("Anna Sidorova",), ("Ivan Petrov",), ("Zq Buyer",)])
        )
    else:
        assert got == rows


def test_token_lookup_end_to_end(
    store: TokenStore, prepare_sql: PrepareRun, engine: Engine
) -> None:
    tok = store.tokenize("Anna Sidorova", NOW)
    p = prepare_sql(f"SELECT id FROM people WHERE full_name = '{tok}'", "sqlite")  # noqa: S608
    with engine.connect() as con:
        assert con.execute(text(p.sql), p.params).fetchall() == [(2,)]
    engine.dispose()
