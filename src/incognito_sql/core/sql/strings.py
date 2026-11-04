"""SQLite's double-quoted strings: a quoted name that names nothing is a string literal."""

from sqlglot import exp

from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.parse import DOUBLE_QUOTED

# SQLite's implicit columns: a name, never a string.
_ROWID = frozenset({"rowid", "oid", "_rowid_"})


def quoted_strings(tree: exp.Expression, catalog: Catalog, dialect: str) -> exp.Expression:
    """Return `tree` with SQLite's double-quoted strings as string literals.

    SQLite reads `"x"` (double quotes only, not `[x]` or `` `x` ``) as a string when no
    column named x is in reach. Here a bare double-quoted name (no qualifier) becomes a
    string only when no catalog column and no alias, CTE or projection name of the
    query is called that, compared without case: then the name can mean nothing else.
    Other dialects are left as they are.
    """
    if dialect != "sqlite":
        return tree
    names = {c.lower() for cols in catalog.columns.values() for c in cols} | _ROWID
    names |= {n.lower() for n in _query_names(tree)}
    for col in list(tree.find_all(exp.Column)):
        ident = col.this
        if (
            not col.table
            and isinstance(ident, exp.Identifier)
            and ident.meta.get(DOUBLE_QUOTED)
            and ident.name.lower() not in names
        ):
            col.replace(exp.Literal.string(ident.name))
    return tree


def _query_names(tree: exp.Expression) -> set[str]:
    found: set[str] = set()
    for node in tree.find_all(exp.Alias, exp.TableAlias, exp.CTE):
        alias = node.alias if not isinstance(node, exp.TableAlias) else node.name
        if alias:
            found.add(alias)
    for table_alias in tree.find_all(exp.TableAlias):
        found.update(col.name for col in table_alias.columns)
    return found
