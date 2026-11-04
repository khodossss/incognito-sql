"""The visible window of the database: tables, usable columns and their classes."""

from incognito_sql.core.config import ColumnClass, Declaration, column_class, column_operations
from incognito_sql.core.config.protection import resolve
from incognito_sql.core.display import entity_keys
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.expand import VISIBLE

DBMS = {
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "sqlite": "SQLite",
    "duckdb": "DuckDB",
    "tsql": "SQL Server (T-SQL)",
}


def describe(decl: Declaration, catalog: Catalog) -> dict[str, object]:
    """Return the DBMS, every table with its usable columns and the number of hidden ones.

    The DBMS tells the model which SQL dialect to write. A hidden column (unmarked, or
    of a class that may not be queried) is only counted, never named. A table of people
    whose key is open names that key as ``person_key``: the model links a row to the
    person's card by it. ``identifier_operations`` lists what may be done with an
    identifier column; a table lists its own for a column whose profile differs.
    ``hidden_in_some_rows`` names the columns a row rule makes NULL in some rows (``*``:
    some rows are left out); the condition is not told.
    """
    default = resolve(decl.protection, decl.protections)
    person_keys = dict(entity_keys(decl, catalog))
    tables: dict[str, dict[str, object]] = {}
    for table in sorted(catalog.columns):
        columns: dict[str, str] = {}
        own: dict[str, list[str]] = {}
        hidden = 0
        for column in catalog.columns[table]:
            cls = column_class(decl, table, column)
            if cls not in VISIBLE:
                hidden += 1
                continue
            columns[column] = str(cls)
            ops = column_operations(decl, table, column)
            if cls is ColumnClass.IDENTIFIER and ops != default:
                own[column] = sorted(ops)
        tables[table] = {"columns": columns, "hidden_columns": hidden}
        if own:
            tables[table]["identifier_operations"] = own
        if table in person_keys:
            tables[table]["person_key"] = person_keys[table]
        masked = _masked(decl, table)
        if masked:
            tables[table]["hidden_in_some_rows"] = masked
    return {
        "dbms": DBMS.get(decl.dialect, decl.dialect),
        "identifier_operations": sorted(default),
        "tables": tables,
    }


def _masked(decl: Declaration, table: str) -> list[str]:
    found: set[str] = set()
    for rule in decl.row_rules:
        if rule.table.lower() == table.lower():
            found |= {"*"} if rule.hide == "*" else {c.lower() for c in rule.hide}
    return sorted(found)
