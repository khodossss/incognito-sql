"""The database read directly: targets of the series, values to look for, and truth.

Read by the service's DSN through a read-only engine, never through the protection.
Queries are built with SQLAlchemy, which writes them in the database's dialect.
"""

from collections.abc import Iterator

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from incognito_sql.core.config import ColumnClass, Declaration
from incognito_sql.core.sql.catalog import reflect
from incognito_sql.levels.cuts import ROWS
from incognito_sql.levels.target import MIN_TARGET, Target

_POOL = 1000  # rows a target is chosen among


def _table(name: str, *columns: str) -> sa.TableClause:
    return sa.table(name, *(sa.column(c) for c in columns))


class DbTruth:
    """The truth of the series: the database compares and finds values itself."""

    def __init__(self, engine: Engine) -> None:
        """Read through ``engine``."""
        self._engine = engine

    def below(self, target: Target, probe: object) -> bool:
        """Tell whether the target's value sorts below ``probe`` in the database."""
        t = _table(target.table, target.key, target.column)
        query = (
            sa.select(sa.func.count())
            .select_from(t)
            .where(t.c[target.key] == target.row, t.c[target.column] < probe)
        )
        with self._engine.connect() as con:
            return bool(con.execute(query).scalar())

    def holds(self, target: Target, value: object) -> bool:
        """Tell whether a row of the target's column holds ``value``."""
        t = _table(target.table, target.column)
        query = sa.select(sa.literal(1)).select_from(t).where(t.c[target.column] == value).limit(1)
        with self._engine.connect() as con:
            return con.execute(query).first() is not None


def identifier_columns(decl: Declaration) -> Iterator[tuple[str, str, str]]:
    """Yield (table, column, key) of every identifier column of an entity table."""
    keys = {e.table: e.pk for e in decl.entities}
    for table in sorted(decl.columns):
        for column, cls in sorted(decl.columns[table].items()):
            if cls is ColumnClass.IDENTIFIER and table in keys:
                yield table, column, keys[table]


def hidden_columns(engine: Engine, decl: Declaration) -> list[tuple[str, str]]:
    """Return (table, column) of every database column the declaration does not name.

    The tables and views are those the server reflects, named as it resolves them.
    """
    out = []
    for table, columns in sorted(reflect(engine, decl.dialect).columns.items()):
        named = decl.columns.get(table.lower(), {})
        out += [(table, c) for c in sorted(columns) if c.lower() not in named]
    return out


def targets(engine: Engine, table: str, column: str, key: str, count: int) -> list[Target]:
    """Return up to ``count`` targets of one column, rows spread over its first ones."""
    t = _table(table, key, column)
    query = sa.select(t.c[key], t.c[column]).where(t.c[column].is_not(None)).order_by(t.c[key])
    with engine.connect() as con:
        rows = con.execute(query.limit(_POOL)).all()
    pool = [
        Target(table, key, row, column, value)
        for row, value in rows
        if isinstance(value, str | int | float) and len(str(value)) >= MIN_TARGET
    ]
    step = max(1, len(pool) // max(count, 1))
    return pool[::step][:count]


def values(engine: Engine, table: str, column: str, cap: int) -> list[object]:
    """Return what is looked for in a column's answers.

    Up to ``cap`` distinct values, and those a cut can show whatever the sample holds:
    the first rows and the extremes.
    """
    t = _table(table, column)
    present = t.c[column].is_not(None)
    queries = [
        sa.select(t.c[column]).where(present).distinct().limit(cap),
        sa.select(t.c[column]).where(present).limit(ROWS),
        sa.select(sa.func.min(t.c[column])).where(present),
        sa.select(sa.func.max(t.c[column])).where(present),
    ]
    found: dict[object, None] = {}
    with engine.connect() as con:
        for query in queries:
            found.update((v, None) for (v,) in con.execute(query) if v is not None)
    return list(found)
