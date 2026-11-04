"""The oracles of one database under one marking: what is hidden, minus what is visible."""

import itertools
import sqlite3
from collections.abc import Iterable, Iterator, Sequence

from bench.external import dbfile, rows
from bench.external.marking import SHOWN, Marking
from bench.external.rowrule import RowRule
from incognito_sql.levels.fragment import Fragments
from incognito_sql.levels.oracle import MIN_LENGTH, Oracle
from incognito_sql.levels.partial import Pieces

_CHUNK = 1 << 20
_APART = "\n|\n"  # a value is whole, so none matches across the bar


def hidden_columns(marking: Marking, schema: dbfile.Schema) -> set[tuple[str, str]]:
    """Return (table, column), lower-cased, of every column not shown as it is."""
    return {
        (t.lower(), c.lower())
        for t, cols in schema.items()
        for c in cols
        if marking.cls(t, c) not in SHOWN
    }


def oracle_for(con: sqlite3.Connection, marking: Marking, schema: dbfile.Schema) -> Oracle:
    """Build the oracle: hidden values, minus those found in shown cells or names.

    A shown column under a rule on rows is hidden in the rows the rule covers: its
    values there are looked for, unless they are shown in another row or column.
    """
    hidden, rules = hidden_columns(marking, schema), marking.rules
    oracle = Oracle(_values(con, schema, hidden, rules, shown=False))
    oracle.drop(_chunks(_visible(con, schema, hidden, rules)))
    return oracle


def parts_for(
    con: sqlite3.Connection, marking: Marking, schema: dbfile.Schema
) -> tuple[Fragments, Pieces]:
    """Build the L2 oracle: hidden values, and their pieces in shown columns and names."""
    hidden, rules = hidden_columns(marking, schema), marking.rules
    fragments = Fragments(_values(con, schema, hidden, rules, shown=False))
    return fragments, Pieces(fragments, _visible(con, schema, hidden, rules))


def _values(
    con: sqlite3.Connection,
    schema: dbfile.Schema,
    hidden: set[tuple[str, str]],
    rules: Sequence[RowRule],
    *,
    shown: bool,
) -> Iterator[object]:
    """Yield the values shown, or hidden: whole hidden columns, and cells a rule hides."""
    for t, cols in schema.items():
        for c in cols:
            if (t.lower(), c.lower()) not in hidden:
                yield from rows.cells(con, t, c, rules, hidden=not shown)
            elif not shown:
                yield from dbfile.values(con, t, c)


def _visible(
    con: sqlite3.Connection,
    schema: dbfile.Schema,
    hidden: set[tuple[str, str]],
    rules: Sequence[RowRule],
) -> Iterator[str]:
    names = [*schema, *(c for cols in schema.values() for c in cols)]
    return itertools.chain(names, map(str, _values(con, schema, hidden, rules, shown=True)))


def changes_nothing(
    con: sqlite3.Connection, schema: dbfile.Schema, closed: Iterable[tuple[str, str]]
) -> bool:
    """Tell whether closing these columns leaves the oracle as it is.

    It does when none of their values is long enough to be looked for, or to hold a
    looked-for value whole (small numbers, short codes): rebuilding the oracle of a
    large database for such a column is minutes of work for nothing.
    """
    names = {(t.lower(), c.lower()): (t, c) for t, cols in schema.items() for c in cols}
    for pair in closed:
        table, column = names[pair]
        if any(len(str(v)) >= MIN_LENGTH for v in dbfile.values(con, table, column)):
            return False
    return True


def _chunks(texts: Iterable[str]) -> Iterator[str]:
    """Join texts into pieces of about ``_CHUNK`` characters; no value spans two texts."""
    piece: list[str] = []
    size = 0
    for text in texts:
        piece.append(text)
        size += len(text) + len(_APART)
        if size >= _CHUNK:
            yield _APART.join(piece)
            piece, size = [], 0
    if piece:
        yield _APART.join(piece)
