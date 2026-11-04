"""The decoy copy of a set's database: the twin a tool runs beside (``bench.external.score``).

Every value of the hidden columns is replaced, and every cell a rule on rows hides; equal
values get equal decoys in every column, so joins and groups keep their shape, and the
rest of the file is kept.
"""

import hashlib
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

from bench.external.dbfile import opened, schema
from bench.external.rowrule import RowRule
from bench.external.rows import covered

_STEPS = (3, 7, 1, 9, 4, 6, 2, 8, 5)  # the decoy's step of each digit place


def decoy_copy(
    source: Path, target: Path, hidden: set[tuple[str, str]], rules: Sequence[RowRule] = ()
) -> Path:
    """Copy ``source`` to ``target`` with every hidden value replaced.

    ``hidden`` holds (table, column) in lower case: every value there is replaced; a
    ``rules`` column only in the rows its rule hides it in. Equal values get equal
    decoys in every column, so joins and groups keep their shape; a tool answers the
    copy as it answers the file, links and keys included, without one hidden value.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    with opened(source) as con, closing(sqlite3.connect(target)) as out:
        con.backup(out)
        out.create_function("decoy", 1, decoy, deterministic=True)
        out.create_function("decoy_text", 1, decoy_text, deterministic=True)
        # a rule's rows are chosen before any value changes: its condition may read a
        # column the rule itself hides
        for i, rule in enumerate(rules):
            out.execute(
                f'CREATE TEMP TABLE ruled_{i} AS SELECT rowid AS id FROM "{rule.table}"'  # noqa: S608
                f" WHERE {covered(rule)}"
            )
        for table, cols in schema(out).items():
            whole = [c for c in cols if (table.lower(), c.lower()) in hidden]
            for column in whole:
                _replace(out, table, column)
            for i, rule in enumerate(rules):
                if rule.table != table.lower():
                    continue
                rows = f"rowid IN (SELECT id FROM temp.ruled_{i})"  # noqa: S608 -- our own table
                for column in (c for c in cols if c not in whole and rule.hides(c.lower())):
                    _replace(out, table, column, rows)
        out.commit()
    return target


def _replace(out: sqlite3.Connection, table: str, column: str, where: str = "1") -> None:
    """Replace the values of one column by their decoys, a unique key staying unique.

    A decoy may be another row's value not yet replaced: with no negative number in the
    column, numbers first move below zero, out of the way, and come back as decoys.
    """
    c = f'"{column}"'
    number = f"typeof({c}) IN ('integer', 'real')"
    negative = f'SELECT count(*) FROM "{table}" WHERE {number} AND {c} < 0'  # noqa: S608
    aside = not out.execute(negative).fetchone()[0]
    if aside:
        out.execute(f'UPDATE "{table}" SET {c} = -{c} - 1 WHERE {number} AND {where}')  # noqa: S608
    back = f"decoy(-{c} - 1)" if aside else f"decoy({c})"
    # text goes over as bytes: text that is not UTF-8 cannot reach a function
    out.execute(
        f"UPDATE \"{table}\" SET {c} = CASE WHEN typeof({c}) = 'text'"  # noqa: S608
        f" THEN decoy_text(CAST({c} AS BLOB)) ELSE {back} END WHERE {where}"
    )


def decoy(value: object) -> str | bytes | int | float | None:
    """Return the decoy of one value: a number stays a number, text stays text.

    A number gets every digit shifted, one to one: a decoy that kept the digits
    (``v + 10**12``) would show the hidden number inside its own.
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        return _digits(value)
    if isinstance(value, bytes):
        return b"d" + hashlib.sha1(value).digest()[:8]  # noqa: S324 -- a label, not a secret
    return decoy_text(str(value).encode())


def _digits(value: float) -> int | float:
    """Shift every digit by a non-zero step of its place: one to one, no digit kept."""
    out, first = [], True
    for i, ch in enumerate(repr(value)):
        if not ch.isdigit():
            out.append(ch)
            continue
        step = _STEPS[i % len(_STEPS)]
        if first:  # a leading digit stays 1-9: the number keeps its number of digits
            out.append(str((int(ch) - 1 + step % 8 + 1) % 9 + 1) if ch != "0" else "0")
        else:
            out.append(str((int(ch) + step) % 10))
        first = False
    return type(value)("".join(out))


def decoy_text(raw: bytes) -> str:
    """Return the decoy of a text value given as its stored bytes."""
    return "d" + hashlib.sha1(raw).hexdigest()[:16]  # noqa: S324 -- a label, not a secret
