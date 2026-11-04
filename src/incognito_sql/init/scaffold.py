"""Render the declaration scaffold: every table present, every column hidden."""

import json

from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.init.hints import name_hint, suggested_class
from incognito_sql.init.report import Samples, reason

_HEADER = (
    "# Scaffold: nothing is visible until you uncomment a column line under its table\n"
    "# and set its class (identifier, quasi, free_text, secret, open).\n"
    "# Lines marked PII? are guesses by name or by a local sample; you decide.\n"
)
_BREAKS = {"\u2028": "\\u2028", "\u2029": "\\u2029", "\x85": "\\x85"}


def quoted(name: str) -> str:
    """Return a double-quoted YAML scalar, so no name is read as a bool or null."""
    text = json.dumps(name, ensure_ascii=False)
    for char, escape in _BREAKS.items():
        text = text.replace(char, escape)
    return text


def _line(
    table: str, column: str, samples: Samples | None, missed: frozenset[tuple[str, str]]
) -> str:
    why = reason(table, column, samples)
    if why is None:
        line = f"  #   {quoted(column)}: open"
    else:
        cls = suggested_class(name_hint(column))
        line = f"  #   {quoted(column)}: {cls}  # PII?: {why}"
    return line + ("  # not sampled" if (table, column) in missed else "")


def scaffold(
    catalog: Catalog,
    samples: Samples | None,
    *,
    missed: frozenset[tuple[str, str]] = frozenset(),
    dsn_env: str = "DATABASE_URL",
    dialect: str = "sqlite",
) -> str:
    """Return YAML that loads as a declaration and hides every column."""
    lines = [_HEADER, f"dsn_env: {quoted(dsn_env)}", f"dialect: {quoted(dialect)}", "columns:"]
    for table, cols in catalog.columns.items():
        lines.append(f"  {quoted(table)}:")
        lines.extend(_line(table, column, samples, missed) for column in cols)
    lines.append("entities: []")
    return "\n".join(lines) + "\n"
