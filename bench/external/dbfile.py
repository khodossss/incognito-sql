"""A set's SQLite database, read directly (never through a tool under test).

The schema, the values of a column, and the reference answer of a query: a query that
fails, runs past ``LIMIT_S`` or returns more than ``MAX_ROWS`` rows has no reference.
"""

import sqlite3
import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from bench.dbms import LIMIT_S

MAX_ROWS = 100  # safedb-mcp caps an answer at 100 rows by default
Schema = dict[str, dict[str, str]]
Rows = list[tuple[object, ...]]


@contextmanager
def opened(path: Path) -> Iterator[sqlite3.Connection]:
    """Open the file read-only; text that is not UTF-8 is decoded with replacement."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
    con.text_factory = lambda b: b.decode("utf-8", errors="replace")
    try:
        yield con
    finally:
        con.close()


def schema(con: sqlite3.Connection) -> Schema:
    """Return {table: {column: declared type}} of the user tables, names as stored."""
    tables = [
        str(name)
        for (name,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        t: {str(c[1]): str(c[2]) for c in con.execute(f'PRAGMA table_info("{t}")')} for t in tables
    }


def values(con: sqlite3.Connection, table: str, column: str) -> Iterator[object]:
    """Yield the distinct non-null values of one column."""
    sql = f'SELECT DISTINCT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'  # noqa: S608
    for (value,) in con.execute(sql):
        yield value


def reference(con: sqlite3.Connection, sql: str, *, ordered: bool) -> Rows | str:
    """Return the rows of ``sql``, or why it has no usable reference.

    The query runs twice, the second time with SQLite reading unordered scans in
    reverse: an answer that changes (ties under ``LIMIT``, ties in an order) depends on
    the scan order, not on the question, and has no single reference.
    """
    first = _run(con, sql, reverse=False)
    if isinstance(first, str):
        return first
    second = _run(con, sql, reverse=True)
    same = first == second if ordered else Counter(first) == Counter(second)
    return first if same else "order-dependent"


def _run(con: sqlite3.Connection, sql: str, *, reverse: bool) -> Rows | str:
    con.execute(f"PRAGMA reverse_unordered_selects = {int(reverse)}")
    timer = threading.Timer(LIMIT_S, con.interrupt)
    timer.daemon = True
    timer.start()
    try:
        rows = con.execute(sql).fetchmany(MAX_ROWS + 1)
    except (sqlite3.Error, sqlite3.Warning, ValueError, OverflowError) as exc:
        return "interrupted" if "interrupt" in str(exc) else "error"
    finally:
        timer.cancel()
        con.execute("PRAGMA reverse_unordered_selects = 0")
    return [tuple(r) for r in rows] if len(rows) <= MAX_ROWS else f"over {MAX_ROWS} rows"
