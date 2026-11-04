"""Reasons a column is a candidate, and the contradictions list."""

from collections.abc import Mapping

from incognito_sql.core.config import ColumnClass, Declaration, verified_columns
from incognito_sql.core.output.detect import looks_personal
from incognito_sql.init.hints import name_hint

Samples = Mapping[tuple[str, str], list[object]]
SAMPLE_REASON = "sample looks personal"
_EXPOSED = (ColumnClass.OPEN, ColumnClass.QUASI)  # a quasi column is judged by values only


def reason(table: str, column: str, samples: Samples | None, *, by_name: bool = True) -> str | None:
    """Name the category that makes a column a candidate (never a value), else None."""
    hint = name_hint(column) if by_name else None
    if hint is not None:
        return f'name hint "{hint}"'
    if samples and any(looks_personal(v) for v in samples.get((table, column), ())):
        return SAMPLE_REASON
    return None


def contradictions(decl: Declaration, samples: Samples | None) -> list[str]:
    """List `table.column: reason`: open columns by name or value, quasi columns by value.

    Columns listed under ``verified_open`` are left out.
    """
    found: list[str] = []
    # Sampled names are the catalog's (e.g. "FullName"); the declaration's are lower case.
    if samples is not None:
        samples = {(t.lower(), c.lower()): v for (t, c), v in samples.items()}
    verified = verified_columns(decl)  # a human checked these: no longer contradictions
    for table, cols in decl.columns.items():
        for column, kind in cols.items():
            if f"{table}.{column}" in verified:
                continue
            by_name = kind is ColumnClass.OPEN
            why = reason(table, column, samples, by_name=by_name) if kind in _EXPOSED else None
            if why is not None:
                found.append(f"{table}.{column}: {why}")
    return found
