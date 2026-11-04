"""Statement deadlines for the file databases, which have no statement timeout of their own."""

import math
import sqlite3
import threading
import time
from typing import Any

from sqlalchemy import Engine, event

_STEPS = 1000  # SQLite VM instructions between deadline checks
_KEY = "incognito_deadline"


def sqlite_deadline(engine: Engine, timeout_s: float) -> None:
    """Abort a SQLite statement (and its fetch) once it has run for `timeout_s`."""

    def connect(dbapi_connection: sqlite3.Connection, record: Any) -> None:  # noqa: ANN401
        until = record.info[_KEY] = [math.inf]
        dbapi_connection.set_progress_handler(lambda: time.monotonic() > until[0], _STEPS)

    def start(conn: Any, *_: object) -> None:  # noqa: ANN401
        conn.info[_KEY][0] = time.monotonic() + timeout_s

    event.listen(engine, "connect", connect)
    event.listen(engine, "before_cursor_execute", start)


def duckdb_deadline(engine: Engine, timeout_s: float) -> None:
    """Interrupt a DuckDB statement (and its fetch) once it has run for `timeout_s`.

    The timer of a statement is cancelled by the next statement and when the
    connection goes back to the pool; an interrupt of an idle connection is a no-op.
    """
    lock = threading.Lock()

    def stop(info: dict[str, Any]) -> None:
        with lock:
            timer = info.pop(_KEY, None)
        if timer is not None:
            timer.cancel()

    def start(conn: Any, *_: object) -> None:  # noqa: ANN401
        stop(conn.info)
        timer = threading.Timer(timeout_s, conn.connection.dbapi_connection.interrupt)
        timer.daemon = True
        with lock:
            conn.info[_KEY] = timer
        timer.start()

    event.listen(engine, "before_cursor_execute", start)
    event.listen(engine, "checkin", lambda _dbapi, record: stop(record.info))
