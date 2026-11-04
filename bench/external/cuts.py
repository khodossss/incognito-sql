"""The L2 cases of a work: the cuts of ``incognito_sql.levels.cuts``, every hidden column.

Written from the marking, one query per hidden column and form: the head and the tail
of the value, as long as a piece must be to count (``incognito_sql.levels.fragment``), the
value cut in two around a separator, and ``MIN``/``MAX``, which return values whole. A
case that shows a value whole is an L1 leak, one that shows a piece is L2.
"""

from bench.external import dbfile
from incognito_sql.levels.cuts import cuts as column_cuts


def cuts(schema: dbfile.Schema, hidden: set[tuple[str, str]]) -> list[tuple[str, str]]:
    """Return (case, query) for every hidden column of ``schema``, in table and column order."""
    return [
        case
        for table in sorted(schema)
        for column in sorted(schema[table])
        if (table.lower(), column.lower()) in hidden
        for case in column_cuts(table, column, "sqlite")
    ]
