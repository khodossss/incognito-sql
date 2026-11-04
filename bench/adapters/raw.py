"""The positive control: plain read-only SQL as the reader, no protection at all."""

import json
import shutil
import sqlite3
import threading
from collections.abc import Mapping

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import NullPool

from bench.adapters.base import ANSWERED, FOREIGN_TOKENS, REFUSED, Info, Outcome, Rows, timed
from bench.dbms import LIMIT_S, Database

INFO = Info(
    name="raw",
    mechanism="none: read-only SQL as the reader (positive control)",
    rung=0,
    install="SQLAlchemy and the DBMS driver",
    command="DBAPI cursor.execute(sql) as the SELECT-only reader",
    tool="(direct)",
    arguments="sql",
)


def reader_engine(db: Database) -> Engine:
    """Open the reader; SQLite and DuckDB files are opened read-only.

    On a server every query gets a fresh session, so nothing one case sets carries into
    the next. In process, nothing may touch other files: SQLite attaches no database
    (ATTACH would create one) and DuckDB has no external access.
    """
    if db.dialect == "sqlite" and db.path is not None:
        engine = create_engine(f"sqlite:///file:{db.path.as_posix()}?mode=ro&uri=true")
        event.listen(engine, "connect", _no_attach)
        return engine
    if db.dialect == "duckdb" and db.path is not None:
        # DuckDB refuses a second in-process connection with other settings: use a copy.
        copy = db.path.with_name(f"raw-{db.path.name}")
        shutil.copyfile(db.path, copy)
        closed = {"read_only": True, "config": {"enable_external_access": False}}
        return create_engine(f"duckdb:///{copy.as_posix()}", connect_args=closed)
    args = {"timeout": LIMIT_S} if db.dialect == "tsql" else {}
    return create_engine(db.url, poolclass=NullPool, connect_args=args)


def _no_attach(connection: sqlite3.Connection, _record: object) -> None:
    connection.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)


class RawAdapter:
    """Send SQL straight to the database; the driver's answer or error is what is read."""

    mode: str | None = None
    tokens: Mapping[str, str] = FOREIGN_TOKENS

    def __init__(self, db: Database, info: Info = INFO) -> None:
        """Connect as the reader of ``db``."""
        self.info, self.dialect = info, db.dialect
        self._engine = reader_engine(db)

    def query(self, sql: str) -> Outcome:
        """Run ``sql``; a database error is a refusal whose text is the driver's message."""
        return timed(lambda: self._run(sql))

    def _run(self, sql: str) -> tuple[str, str, Rows | None]:
        # The DBAPI cursor directly: with no parameters no driver rewrites `%` in the SQL.
        try:
            with self._engine.connect() as conn:
                dbapi = conn.connection.dbapi_connection
                watchdog = self._watchdog(dbapi)
                cursor = dbapi.cursor()  # type: ignore[union-attr]
                try:
                    cursor.execute(sql)
                    rows = [list(r) for r in cursor.fetchall()] if cursor.description else []
                finally:
                    watchdog.cancel()
                    cursor.close()
                    conn.rollback()
        except Exception as exc:  # noqa: BLE001 -- whatever the driver raises is its refusal
            return REFUSED, str(exc), None
        return ANSWERED, json.dumps(rows, ensure_ascii=False, default=str), rows

    def _watchdog(self, connection: object) -> threading.Timer:
        """Interrupt an in-process query (SQLite, DuckDB) that outlives ``LIMIT_S``.

        Servers enforce the limit themselves: the reader's statement timeout (Postgres,
        MySQL) or the driver's query timeout (SQL Server).
        """
        stop = getattr(connection, "interrupt", None)
        timer = threading.Timer(LIMIT_S, stop if callable(stop) else lambda: None)
        timer.daemon = True
        if self.dialect in {"sqlite", "duckdb"}:
            timer.start()
        return timer

    def channels(self) -> dict[str, str]:
        """Return nothing: the driver writes no side channel."""
        return {}

    def static(self) -> str:
        """Return nothing: there is no tool listing."""
        return ""

    def close(self) -> None:
        """Dispose of the engine."""
        self._engine.dispose()
