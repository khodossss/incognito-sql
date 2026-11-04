import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.dialects import mysql, postgresql
from sqlalchemy.engine import URL
from sqlalchemy.exc import DatabaseError

from incognito_sql.core.db import engine_args, make_engine
from incognito_sql.core.sql.catalog import reflect, type_text

from .reflected import UnknownZone


def test_reflect_lists_tables_and_columns(people_db: Path) -> None:
    engine = make_engine(f"sqlite:///{people_db}", "sqlite")
    try:
        catalog = reflect(engine, "sqlite")
    finally:
        engine.dispose()
    assert catalog.columns["people"]["full_name"] == "TEXT"
    assert catalog.columns["people"]["phone"] == "BIGINT"
    assert catalog.columns["people"]["id"] == "INTEGER"
    assert "cities" in catalog.columns
    assert "sqlite_master" not in catalog.columns
    assert not any(t.startswith("sqlite_") for t in catalog.columns)


def test_write_through_engine_fails(people_db: Path) -> None:
    engine = make_engine(f"sqlite:///{people_db}", "sqlite")
    try:
        with pytest.raises(DatabaseError), engine.begin() as con:
            con.execute(text("INSERT INTO people (id) VALUES (2)"))
    finally:
        engine.dispose()


def test_memory_sqlite_rejected() -> None:
    with pytest.raises(ValueError, match="in-memory"):
        make_engine("sqlite:///:memory:", "sqlite")


def test_unsupported_dialect() -> None:
    with pytest.raises(ValueError, match="unsupported dialect"):
        make_engine("oracle://u@h/d", "oracle")


def test_postgres_engine_args() -> None:
    url, connect_args = engine_args("postgresql+psycopg://u:p@localhost/d", "postgres", 2500)
    assert url == "postgresql+psycopg://u:p@localhost/d"
    options = connect_args["options"]
    assert "-c default_transaction_read_only=on" in options
    assert "-c statement_timeout=2500" in options


def test_sqlite_engine_args_read_only(tmp_path: Path) -> None:
    url, connect_args = engine_args(f"sqlite:///{tmp_path / 'a b.db'}", "sqlite", 1)
    assert isinstance(url, URL)
    assert url.query == {"mode": "ro", "uri": "true"}
    assert url.database is not None
    assert url.database.endswith("a%20b.db")
    assert connect_args == {}


def _fails(engine: Engine, sql: str) -> bool:
    try:
        with engine.begin() as con:
            con.execute(text(sql))
    except DatabaseError:
        return True
    return False


def test_sqlite_engine_is_locked_to_reads(people_db: Path, tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{people_db}", "sqlite")
    new_db = tmp_path / "new.db"
    try:
        assert _fails(engine, f"ATTACH DATABASE '{new_db}' AS n")
        assert not new_db.exists()
        assert _fails(engine, "CREATE TEMP TABLE t (x INTEGER)")
        assert _fails(engine, "PRAGMA query_only=0")
        assert _fails(engine, "PRAGMA journal_mode=wal")
        assert not _fails(engine, "SELECT full_name FROM people")
        assert "people" in reflect(engine, "sqlite").columns
    finally:
        engine.dispose()


def test_view_and_varchar_type(tmp_path: Path) -> None:
    path = tmp_path / "v.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (name VARCHAR(10))")
    con.execute("CREATE VIEW v AS SELECT name FROM t")
    con.commit()
    con.close()
    engine = make_engine(f"sqlite:///{path}", "sqlite")
    try:
        columns = reflect(engine, "sqlite").columns
    finally:
        engine.dispose()
    assert columns["v"]["name"] == "VARCHAR(10)"
    assert columns["t"]["name"] == "VARCHAR(10)"


def test_path_with_special_characters(tmp_path: Path) -> None:
    folder = tmp_path / "a#b%c d"
    folder.mkdir()
    path = folder / "x#y%20.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (name TEXT)")
    con.commit()
    con.close()
    dsn = URL.create("sqlite", database=str(path)).render_as_string()
    before = sorted(p.name for p in tmp_path.rglob("*"))
    engine = make_engine(dsn, "sqlite")
    try:
        assert "t" in reflect(engine, "sqlite").columns
    finally:
        engine.dispose()
    assert sorted(p.name for p in tmp_path.rglob("*")) == before


def test_nonpositive_timeout_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        engine_args("postgresql://u@h/d", "postgres", 0)


def test_type_text_keeps_the_flags_a_type_name_leaves_out() -> None:
    assert type_text(mysql.BIGINT(unsigned=True)) == "BIGINT UNSIGNED"
    assert type_text(mysql.BIGINT()) == "BIGINT"
    assert type_text(postgresql.TIMESTAMP(timezone=True)) == "TIMESTAMP WITH TIME ZONE"
    assert type_text(postgresql.TIME()) == "TIME"
    assert type_text(mysql.DATETIME(fsp=3)) == "DATETIME(3)"
    assert type_text(mysql.TIME(fsp=6)) == "TIME(6)"
    assert type_text(mysql.DATETIME()) == "DATETIME"
    assert type_text(UnknownZone()) == ""  # matches nothing
