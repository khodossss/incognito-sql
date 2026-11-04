"""Targets of the inference series on a set's SQLite file, and the truth about them.

A target row is addressed by a shown column whose values are unique in its table, so a
series asks about that row alone (``incognito_sql.levels.target``).
"""

import sqlite3
from collections.abc import Iterator

from bench.external import dbfile
from bench.external.hidden import hidden_columns
from bench.external.marking import Marking
from incognito_sql.levels.target import MIN_TARGET, Target


def targets(con: sqlite3.Connection, marking: Marking, count: int) -> list[Target]:
    """Return up to ``count`` targets, one hidden column after another, rows spread."""
    schema = dbfile.schema(con)
    hidden = hidden_columns(marking, schema)
    pools = [list(_rows(con, t, c, k)) for t, c, k in _columns(con, schema, hidden)]
    out: list[Target] = []
    for depth in range(count):
        for pool in pools:
            at = depth * max(1, len(pool) // count)
            if len(out) < count and at < len(pool):
                out.append(pool[at])
    return out


def _columns(
    con: sqlite3.Connection, schema: dbfile.Schema, hidden: set[tuple[str, str]]
) -> Iterator[tuple[str, str, str]]:
    for table in sorted(schema):
        keys = [c for c in schema[table] if (table.lower(), c.lower()) not in hidden]
        key = next((k for k in keys if _unique(con, table, k)), None)
        if key is None:
            continue
        for column in sorted(schema[table]):
            if (table.lower(), column.lower()) in hidden:
                yield table, column, key


def _unique(con: sqlite3.Connection, table: str, column: str) -> bool:
    sql = f'SELECT count(*) = count(DISTINCT "{column}") AND count(*) > 0 FROM "{table}"'  # noqa: S608
    return bool(con.execute(sql).fetchone()[0])


def _rows(con: sqlite3.Connection, table: str, column: str, key: str) -> Iterator[Target]:
    sql = (
        f'SELECT "{key}", "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'  # noqa: S608
        f' AND length("{column}") >= {MIN_TARGET} ORDER BY "{key}"'
    )
    for row, value in con.execute(sql).fetchmany(1000):
        if isinstance(value, str | int | float):
            yield Target(table, key, row, column, value)


class SqliteTruth:
    """The truth of the inference series, read from the set's SQLite file."""

    def __init__(self, con: sqlite3.Connection) -> None:
        """Read through ``con``, the file opened read-only."""
        self._con = con

    def below(self, target: Target, probe: object) -> bool:
        """Tell whether the target's value sorts below ``probe`` in SQLite."""
        t = target
        sql = f'SELECT count(*) FROM "{t.table}" WHERE "{t.key}" = ? AND "{t.column}" < ?'  # noqa: S608
        return bool(self._con.execute(sql, (t.row, probe)).fetchone()[0])

    def holds(self, target: Target, value: object) -> bool:
        """Tell whether a row of the target's column holds ``value``."""
        sql = f'SELECT 1 FROM "{target.table}" WHERE "{target.column}" = ? LIMIT 1'  # noqa: S608
        return self._con.execute(sql, (value,)).fetchone() is not None
