"""Qualify a parsed query against the catalog and trace its columns."""

from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

from incognito_sql.core.config import Declaration
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.allowlist import check_nodes
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.colref import ColumnRef
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.order_keys import check_order_keys
from incognito_sql.core.sql.shadow import check_aliases, check_names, mark_written_aliases
from incognito_sql.core.sql.stars import check_star_places
from incognito_sql.core.sql.strings import quoted_strings

__all__ = ["ColumnRef", "qualify_tree", "source_of"]

# The schema a bare table name means; a table in any other schema is unknown.
# Dialects not listed here (MySQL: a qualifier is another database) accept none.
_DEFAULT_DB = {"postgres": "public", "sqlite": "main", "duckdb": "main", "tsql": "dbo"}


def qualify_tree(
    tree: exp.Expression, catalog: Catalog, dialect: str, *, allow_rewrite: bool = False
) -> exp.Expression:
    """Return a qualified copy of `tree`: every column bound to its source.

    Unknown tables, unknown columns and tables outside the default schema raise
    Rejection(UNKNOWN_COLUMN); a name that several sources carry raises
    Rejection(AMBIGUOUS_COLUMN), and so do names that shadow other names
    (duplicate CTE names or table aliases, a CTE named like a table or alias, a
    projection alias equal to a source column name); a whole-row reference
    raises Rejection(UNKNOWN_COLUMN). The input tree is not changed.
    `allow_rewrite` admits the random sort key of SQL the server rewrote. A SQLite
    double-quoted name that names nothing is taken as the string SQLite reads.
    """
    tree = quoted_strings(tree.copy(), catalog, dialect)
    mark_written_aliases(tree)
    # Every name resolves to one source: the narrow accepted shape.
    check_names(tree, catalog)
    # Before qualify: it resolves positions without star expansion.
    check_star_places(tree)
    check_order_keys(tree, allow_rewrite=allow_rewrite)
    schema = _schema(catalog, dialect)
    qualified: exp.Expression | None
    # The optimizer's messages quote the SQL: never chain them.
    try:
        qualified = qualify(
            tree.copy(),
            schema=schema,
            dialect=dialect,
            expand_stars=False,
            validate_qualify_columns=True,
            quote_identifiers=False,
        )
    except Exception:  # noqa: BLE001
        qualified = None
    if qualified is None:
        reason = Reason.AMBIGUOUS_COLUMN if _ambiguous(tree, catalog) else Reason.UNKNOWN_COLUMN
        raise Rejection(reason)
    # A whole-row reference (`SELECT p FROM people p`) qualifies to a TableColumn.
    if qualified.find(exp.TableColumn) is not None:
        raise Rejection(Reason.UNKNOWN_COLUMN)
    # The optimizer may add nodes: the result must pass the same allowlist.
    # Placeholders were already admitted or refused on the input tree.
    check_nodes(qualified, allow_placeholders=True)
    _check_tables(qualified, catalog, dialect)
    check_aliases(qualified, catalog)
    return qualified


def source_of(col: exp.Column, tree: exp.Expr, catalog: Catalog, decl: Declaration) -> ColumnRef:
    """Trace `col` of the qualified `tree` through CTEs and subqueries to a base column."""
    return Lineage(tree, catalog, decl).source_of(col)


def _schema(catalog: Catalog, dialect: str) -> dict[str, object]:
    # Quoted, so the optimizer takes each name as it is and does not fold its case.
    def quoted(name: str) -> str:
        return exp.to_identifier(name, quoted=True).sql(dialect=dialect)

    return {
        quoted(table): {quoted(column): kind for column, kind in cols.items()}
        for table, cols in catalog.columns.items()
    }


def _check_tables(tree: exp.Expr, catalog: Catalog, dialect: str) -> None:
    default_db = _DEFAULT_DB.get(dialect)
    seen: set[int] = set()
    for scope in traverse_scope(tree):
        for node, source in scope.selected_sources.values():
            seen.add(id(node))
            if not isinstance(source, exp.Table):
                continue
            if source.db and source.db != default_db:
                raise Rejection(Reason.UNKNOWN_COLUMN)
            if source.name not in catalog.columns:
                raise Rejection(Reason.UNKNOWN_COLUMN)
    # A table no scope accounts for cannot be traced: a guard against a scope gap (none known).
    if any(id(table) not in seen for table in tree.find_all(exp.Table)):
        raise Rejection(Reason.UNKNOWN_COLUMN)


def _ambiguous(tree: exp.Expr, catalog: Catalog) -> bool:
    # Runs on the unqualified tree, only to name the reason of a failed qualify.
    try:
        scopes = traverse_scope(tree)
    except Exception:  # noqa: BLE001
        return False
    for scope in scopes:
        for col in scope.unqualified_columns:
            name = col.name.lower()
            holders = [
                s
                for s in scope.sources.values()
                if (
                    catalog.column(catalog.table(s.name) or "", name) is not None
                    if isinstance(s, exp.Table)
                    else isinstance(s.expression, exp.Query) and name in s.expression.named_selects
                )
            ]
            if len(holders) > 1:
                return True
    return False
