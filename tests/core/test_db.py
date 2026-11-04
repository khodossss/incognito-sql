"""Read-only and timeout settings per dialect, without a server."""

from pathlib import Path

import duckdb
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from incognito_sql.core.db import _on_connect, engine_args, make_engine, session_sql


def test_mysql_session_is_read_only_with_a_timeout() -> None:
    assert engine_args("mysql+pymysql://u:p@h/d", "mysql", 2500) == ("mysql+pymysql://u:p@h/d", {})
    statements = session_sql("mysql", 2500)
    assert statements[:2] == [
        "SET SESSION TRANSACTION READ ONLY",
        "SET SESSION max_execution_time = 2500",
    ]
    assert "NO_BACKSLASH_ESCAPES" in statements[2]
    assert session_sql("postgres", 2500) == []


def test_tsql_timeout_is_whole_seconds_rounded_up() -> None:
    assert engine_args("mssql+pymssql://u:p@h/d", "tsql", 2500)[1] == {"timeout": 3}


def test_duckdb_opens_read_only_without_external_access() -> None:
    _, args = engine_args("duckdb:///w.duckdb", "duckdb", 1)
    assert args == {
        "read_only": True,
        "config": {"enable_external_access": False, "lock_configuration": True},
    }


@pytest.mark.parametrize("query", ["access_mode=read_write", "Enable_External_Access=true"])
def test_duckdb_dsn_cannot_reopen_access(query: str) -> None:
    with pytest.raises(ValueError, match="access settings"):
        engine_args(f"duckdb:///w.duckdb?{query}", "duckdb", 1)


def test_unsupported_dialect_and_timeout() -> None:
    with pytest.raises(ValueError, match="unsupported dialect"):
        engine_args("oracle://u@h/d", "oracle", 1)
    with pytest.raises(ValueError, match="positive"):
        engine_args("mysql://u@h/d", "mysql", 0)


def test_session_statements_run_on_connect() -> None:
    log: list[str] = []

    class Cursor:
        def execute(self, sql: str) -> None:
            log.append(sql)

        def close(self) -> None:
            log.append("closed")

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

    _on_connect(["SET a", "SET b"])(Connection(), None)
    assert log == ["SET a", "SET b", "closed"]


def test_duckdb_engine_cannot_write_or_read_files(tmp_path: Path) -> None:
    path = tmp_path / "w.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE t (x INTEGER)")
    (tmp_path / "f.csv").write_text("x\n1\n", encoding="utf-8")
    engine = make_engine(f"duckdb:///{path.as_posix()}", "duckdb")
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM t")).scalar() == 0
        csv = (tmp_path / "f.csv").as_posix()
        for sql, why in (
            ("INSERT INTO t VALUES (1)", "read-only"),
            (f"SELECT * FROM '{csv}'", "disabled"),  # noqa: S608 -- a test path
        ):
            with pytest.raises(DBAPIError, match=why), engine.connect() as conn:
                conn.execute(text(sql))
    finally:
        engine.dispose()
