"""Read-only database engines."""

import math
import os
import sqlite3
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url

from incognito_sql.core.deadline import duckdb_deadline, sqlite_deadline

DIALECTS = ("postgres", "sqlite", "mysql", "duckdb", "tsql")
DEFAULT_STATEMENT_TIMEOUT_MS = 10_000
_MEMORY_NAMES = {"", ":memory:"}
_ALLOWED_OPS = frozenset(
    {sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
)
# Reflection pragmas only; any other pragma (query_only, journal_mode, ...) is denied.
_ALLOWED_PRAGMAS = frozenset(
    {
        "table_info",
        "table_xinfo",
        "table_list",
        "index_list",
        "index_info",
        "index_xinfo",
        "foreign_key_list",
        "database_list",
    }
)
_DEADLINES = {"sqlite": sqlite_deadline, "duckdb": duckdb_deadline}
# DuckDB settings the engine fixes; a DSN query would override them.
_DUCKDB_FIXED = {"enable_external_access": False, "lock_configuration": True}
_DUCKDB_LOCKED_KEYS = {*_DUCKDB_FIXED, "access_mode"}
# Drop NO_BACKSLASH_ESCAPES from the session's sql_mode, keep the rest.
_MYSQL_MODE = (
    "SET SESSION sql_mode = TRIM(BOTH ',' FROM "
    "REPLACE(CONCAT(',', @@SESSION.sql_mode, ','), ',NO_BACKSLASH_ESCAPES,', ','))"
)


def _authorizer(
    op: int, arg1: str | None, _arg2: str | None, _db: str | None, _src: str | None
) -> int:
    if op in _ALLOWED_OPS:
        return sqlite3.SQLITE_OK
    if op == sqlite3.SQLITE_PRAGMA and arg1 is not None and arg1.lower() in _ALLOWED_PRAGMAS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _lock_sqlite(dbapi_connection: sqlite3.Connection, _record: object) -> None:
    dbapi_connection.execute("PRAGMA query_only=ON")
    dbapi_connection.set_authorizer(_authorizer)


def _sqlite_url(dsn: str) -> URL:
    url = make_url(dsn)
    if url.database in _MEMORY_NAMES or url.database is None:
        msg = "in-memory SQLite is not supported"
        raise ValueError(msg)
    path = url.database.replace("\\", "/") if os.name == "nt" else url.database
    database = f"file:{quote(path, safe='/:')}"
    return URL.create("sqlite", database=database, query={"mode": "ro", "uri": "true"})


def engine_args(
    dsn: str, dialect: str, statement_timeout_ms: int
) -> tuple[str | URL, dict[str, Any]]:
    """Return the URL and driver arguments that make a connection read-only."""
    if statement_timeout_ms <= 0:
        msg = "statement_timeout_ms must be positive"
        raise ValueError(msg)
    if dialect == "sqlite":
        return _sqlite_url(dsn), {}
    if dialect == "postgres":
        options = f"-c default_transaction_read_only=on -c statement_timeout={statement_timeout_ms}"
        return dsn, {"options": options}
    if dialect == "mysql":
        return dsn, {}  # the session is set on connect: see session_sql
    if dialect == "tsql":
        return dsn, {"timeout": math.ceil(statement_timeout_ms / 1000)}
    if dialect == "duckdb":
        if _DUCKDB_LOCKED_KEYS & {k.lower() for k in make_url(dsn).query}:
            msg = "the DuckDB DSN may not set access settings"
            raise ValueError(msg)
        return dsn, {"read_only": True, "config": dict(_DUCKDB_FIXED)}
    msg = "unsupported dialect"
    raise ValueError(msg)


def session_sql(dialect: str, statement_timeout_ms: int) -> list[str]:
    """Return the statements each new connection runs first (MySQL: read-only, timeout)."""
    if dialect != "mysql":
        return []
    return [
        "SET SESSION TRANSACTION READ ONLY",
        f"SET SESSION max_execution_time = {int(statement_timeout_ms)}",
        _MYSQL_MODE,
    ]


def _on_connect(statements: list[str]) -> Callable[[Any, object], None]:
    def run(dbapi_connection: Any, _record: object) -> None:  # noqa: ANN401 -- any DB-API connection
        cursor = dbapi_connection.cursor()
        try:
            for statement in statements:
                cursor.execute(statement)
        finally:
            cursor.close()

    return run


def make_engine(
    dsn: str, dialect: str, *, statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS
) -> Engine:
    """Create an engine that cannot write: a read-only file or session, and a query timeout.

    The real guard is a database login that may only SELECT; SQL Server has no
    read-only session, so there it is the only guard.
    """
    url, connect_args = engine_args(dsn, dialect, statement_timeout_ms)
    engine = create_engine(url, connect_args=connect_args)
    if dialect == "sqlite":
        event.listen(engine, "connect", _lock_sqlite)
    if dialect in _DEADLINES:  # no statement timeout of their own
        _DEADLINES[dialect](engine, statement_timeout_ms / 1000)
    statements = session_sql(dialect, statement_timeout_ms)
    if statements:
        event.listen(engine, "connect", _on_connect(statements))
    return engine
