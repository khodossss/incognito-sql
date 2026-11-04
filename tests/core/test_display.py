"""Entity keys for labels: capped, typed per column, empty on any error."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from incognito_sql.core.config import ColumnClass, Declaration, Entity
from incognito_sql.core.config.row_rules import RowRule
from incognito_sql.core.db import make_engine
from incognito_sql.core.display import MAX_IDS, DisplayIds
from incognito_sql.core.sql.catalog import Catalog, reflect
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.store import TokenStore

ID = ColumnClass.IDENTIFIER
DECL = Declaration(
    dsn_env="DSN",
    dialect="sqlite",
    columns={"people": {"id": ColumnClass.OPEN, "full_name": ID, "phone": ID}},
    entities=[Entity(table="people", pk="id")],
)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    path = tmp_path / "p.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT, phone BIGINT)")
    con.executemany(
        "INSERT INTO people VALUES (?, 'Ivan Petrov', ?)", [(i, 5550100 + i) for i in range(30)]
    )
    con.commit()
    con.close()
    eng = make_engine(f"sqlite:///{path}", "sqlite")
    yield eng
    eng.dispose()


@pytest.fixture
def store(tmp_path: Path) -> Iterator[TokenStore]:
    s = TokenStore(tmp_path / "t.db", Cipher(bytes(range(32))), "db:x", ttl_s=None)
    yield s
    s.close()


def test_keys_are_capped(engine: Engine, store: TokenStore) -> None:
    keys = DisplayIds(DECL, reflect(engine, "sqlite"), store, engine)("Ivan Petrov")
    assert keys == {"people": list(range(MAX_IDS))}


def test_numeric_column_takes_only_numbers(engine: Engine, store: TokenStore) -> None:
    ids = DisplayIds(DECL, reflect(engine, "sqlite"), store, engine)
    assert ids("Anna Ivanova") == {}
    assert ids(5550107) == {"people": [7]}


def test_any_error_gives_no_keys(engine: Engine, store: TokenStore) -> None:
    ghost = Catalog(columns={"ghosts": {"id": "INTEGER", "full_name": "TEXT"}})  # no such table
    decl = DECL.model_copy(
        update={
            "columns": {"ghosts": {"id": ColumnClass.OPEN, "full_name": ID}},
            "entities": [Entity(table="ghosts", pk="id")],
        }
    )
    ids = DisplayIds(decl, ghost, store, engine)
    assert ids("Ivan Petrov") == {}  # labels stay lenient
    with pytest.raises(OperationalError):  # the strict lookup lets the error out
        ids.find("Ivan Petrov")


def test_reserved_and_mixed_case_names_are_quoted(tmp_path: Path, store: TokenStore) -> None:
    path = tmp_path / "q.db"
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE "order" ("select" INTEGER PRIMARY KEY, "FullName" TEXT)')
    con.execute("INSERT INTO \"order\" VALUES (4, 'Ivan Petrov')")
    con.commit()
    con.close()
    eng = make_engine(f"sqlite:///{path}", "sqlite")
    decl = Declaration(
        dsn_env="DSN",
        dialect="sqlite",
        columns={"order": {"select": ColumnClass.OPEN, "fullname": ID}},
        entities=[Entity(table="order", pk="select")],
    )
    try:
        assert DisplayIds(decl, reflect(eng, "sqlite"), store, eng)("Ivan Petrov") == {"order": [4]}
    finally:
        eng.dispose()


def test_stored_forms_the_column_cannot_hold_are_not_looked_up(
    tmp_path: Path, store: TokenStore
) -> None:
    path = tmp_path / "d.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE people (id INTEGER, full_name VARCHAR, born DATE, e ENUM('a'))")
        con.execute("INSERT INTO people VALUES (1, 'not a date', '2020-01-01', 'a')")
    columns = {"people": {"id": ColumnClass.OPEN, "full_name": ID, "born": ID, "e": ID}}
    decl = DECL.model_copy(update={"dialect": "duckdb", "columns": columns})
    eng = make_engine(f"duckdb:///{path.as_posix()}", "duckdb")
    try:
        ids = DisplayIds(decl, reflect(eng, "duckdb"), store, eng)
        assert ids.find("not a date") == {"people": [1]}  # no error from the DATE column
        assert ids.find("2020-01-01") == {"people": [1]}
        assert ids.find("a") == {}  # an enumerated column is never looked up
    finally:
        eng.dispose()


def test_a_row_rule_hides_keys_from_the_model_not_from_the_card(
    engine: Engine, store: TokenStore
) -> None:
    ruled = DECL.model_copy(
        update={"row_rules": [RowRule(table="people", hide="*", where="id < 25")]}
    )
    catalog = reflect(engine, "sqlite")
    assert DisplayIds(ruled, catalog, store, engine)("Ivan Petrov") == {
        "people": [25, 26, 27, 28, 29]
    }
    card = DisplayIds(ruled, catalog, store, engine, for_model=False)("Ivan Petrov")
    assert card == {"people": list(range(MAX_IDS))}
