"""Enumerated types reflect as ENUM, and DuckDB keeps the case of their labels."""

from pathlib import Path

import duckdb
from sqlalchemy.dialects import mysql, postgresql

from incognito_sql.core.db import make_engine
from incognito_sql.core.sql.catalog import reflect, type_text


def test_enumerated_types_are_named_enum() -> None:
    assert type_text(postgresql.ENUM("calm", "busy", name="mood")) == "ENUM"  # not VARCHAR(4)
    assert type_text(mysql.ENUM("calm", "busy")) == "ENUM"


def test_duckdb_enum_labels_keep_their_case(tmp_path: Path) -> None:
    path = tmp_path / "enums.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE t (e ENUM('calm', 'Busy'))")
    engine = make_engine(f"duckdb:///{path.as_posix()}", "duckdb")
    try:
        catalog = reflect(engine, "duckdb")
    finally:
        engine.dispose()
    assert catalog.columns["t"]["e"] == "ENUM('calm', 'Busy')"
