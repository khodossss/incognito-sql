"""The gateway's rules on rows, applied to a set's SQLite file directly.

A rule hides its columns (or the whole row, ``"*"``) where its condition is true or
unknown (NULL), as the gateway does. The oracle reads the cells a rule hides and those
it leaves; a reference answer is computed on a copy with the rules applied, as the
gateway answers.
"""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing
from pathlib import Path

from bench.external.rowrule import RowRule


def covered(rule: RowRule) -> str:
    """Return the SQL condition of the rows ``rule`` hides: its ``where`` true or NULL."""
    return f"(NOT ({rule.where})) IS NOT 1"


def cells(
    con: sqlite3.Connection,
    table: str,
    column: str,
    rules: Sequence[RowRule],
    *,
    hidden: bool,
) -> Iterator[object]:
    """Yield the distinct non-null values of ``column`` in the rows the rules hide it in.

    With ``hidden=False``, the values in the rows they leave it in.
    """
    mine = [r for r in rules if r.table == table.lower() and r.hides(column.lower())]
    if not mine:
        if not hidden:
            yield from _distinct(con, table, column, "1")
        return
    any_hides = " OR ".join(f"({covered(r)})" for r in mine)
    yield from _distinct(con, table, column, any_hides if hidden else f"NOT ({any_hides})")


def masked_copy(source: Path, target: Path, rules: Sequence[RowRule]) -> Path:
    """Copy ``source`` to ``target`` with every rule applied: cells NULL, rows gone."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    source_url = f"file:{source.as_posix()}?mode=ro"
    with (
        closing(sqlite3.connect(source_url, uri=True)) as con,
        closing(sqlite3.connect(target)) as out,
    ):
        con.backup(out)
        for rule in rules:  # a condition reads no column a rule hides: order is free
            where = covered(rule)
            if rule.hide:
                nulls = ", ".join(f'"{c}" = NULL' for c in rule.hide)
                out.execute(f'UPDATE "{rule.table}" SET {nulls} WHERE {where}')  # noqa: S608
            else:
                out.execute(f'DELETE FROM "{rule.table}" WHERE {where}')  # noqa: S608
        out.commit()
    return target


def _distinct(con: sqlite3.Connection, table: str, column: str, where: str) -> Iterator[object]:
    sql = (
        f'SELECT DISTINCT "{column}" FROM "{table}"'  # noqa: S608 -- names from the schema
        f' WHERE "{column}" IS NOT NULL AND ({where})'
    )
    for (value,) in con.execute(sql):
        yield value
