"""Grouped queries: no value may come from an arbitrary row of a group."""

from sqlglot import exp

from incognito_sql.core.config.forms import Form, forms
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.order_keys import strip_parens
from incognito_sql.core.sql.shape import branches, holder, is_star

_NESTED = (exp.Query, exp.Subquery)
# DBMSs that accept a column grouped through its table's primary key; DuckDB and SQL
# Server refuse it themselves.
_KEYED_DIALECTS = frozenset({"sqlite", "postgres", "mysql"})


def check_grouping(tree: exp.Expr, lin: Lineage) -> None:
    """Refuse every value SQLite would take from whichever row the scan meets.

    In a SELECT with GROUP BY, or with an aggregate in its projection or HAVING,
    every column outside an aggregate in the projection, HAVING or ORDER BY must
    be (or sit inside) a GROUP BY key expression; so must every column that a
    nested query there reads from this SELECT's own sources. A literal GROUP BY
    key groups nothing; a bare ORDER BY name that is an output alias stands for
    that (checked) output. An aggregate is refused when the innermost query whose
    columns its argument reads, at any depth, encloses the query holding it: it
    would aggregate that query. So is an unqualified name inside an aggregate
    that is an output alias of the query holding it: SQLite reads it as the
    aliased expression. A column of a base table is grouped when the whole primary
    key of its range variable is among the keys: the key fixes the row. A key that
    can hold NULL counts only where the database's profile admits that form; one a
    row rule hides never counts. Runs on the qualified tree. Raises Rejection(NODE_NOT_ALLOWED).
    """
    for agg in tree.find_all(exp.AggFunc):
        if _belongs_outside(agg, lin) or _names_alias(agg):
            raise Rejection(Reason.NODE_NOT_ALLOWED)
    for select in tree.find_all(exp.Select):
        having = select.args.get("having")
        parts = [*select.expressions, *([having] if having is not None else [])]
        group = select.args.get("group")
        if group is None and not any(_has_aggregate(p) for p in parts):
            continue
        keys = [strip_parens(k) for k in (group.expressions if group is not None else [])]
        keys = [k for k in keys if not isinstance(k, exp.Literal)]
        order = select.args.get("order")
        aliases = {p.alias for p in select.expressions if isinstance(p, exp.Alias)}
        for ordered in order.expressions if order is not None else []:
            key = strip_parens(ordered.this)
            if not (isinstance(key, exp.Column) and not key.table and key.name in aliases):
                parts.append(key)
        if any(_ungrouped(p, keys, select, lin) for p in parts):
            raise Rejection(Reason.NODE_NOT_ALLOWED)


def _has_aggregate(node: exp.Expr) -> bool:
    # An aggregate over a window does not group the query.
    if isinstance(node, exp.AggFunc):
        return True
    if isinstance(node, (*_NESTED, exp.Window)):
        return False
    return any(_has_aggregate(c) for c in node.iter_expressions())


def _ungrouped(node: exp.Expr, keys: list[exp.Expr], select: exp.Select, lin: Lineage) -> bool:
    if isinstance(node, exp.Window):
        func = node.this
        if isinstance(func, exp.AggFunc):
            # A window aggregate reads each row of the grouped result, not the group: its
            # argument must be grouped like any other value (SUM(x) OVER would read the
            # row the scan met first).
            parts = [
                *func.iter_expressions(),
                *(c for c in node.iter_expressions() if id(c) != id(func)),
            ]
            return any(_ungrouped(c, keys, select, lin) for c in parts)
    if isinstance(node, exp.AggFunc) or any(node == k for k in keys):
        return False
    if isinstance(node, _NESTED):
        # A nested query may read this SELECT's row: only through grouped columns.
        return any(
            col.table
            and _owner(col, lin) is select
            and not any(col == k for k in keys)
            and not _keyed(col, keys, lin)
            for col in node.find_all(exp.Column)
        )
    if isinstance(node, exp.Column):
        return not _keyed(node, keys, lin)
    if isinstance(node, exp.Star) or is_star(node):
        return True
    return any(_ungrouped(c, keys, select, lin) for c in node.iter_expressions())


def _keyed(col: exp.Column, keys: list[exp.Expr], lin: Lineage) -> bool:
    # Whether the whole primary key of the column's base table, on the same range
    # variable, is among the GROUP BY keys.
    scope = lin.owning_scope(col) if col.table else None
    source = scope.selected_sources[col.table][1] if scope is not None else None
    if not isinstance(source, exp.Table):
        return False
    if lin.decl.dialect not in _KEYED_DIALECTS:
        return False
    key = lin.catalog.keys.get(source.name)
    loose = Form.NULLABLE_KEY_GROUP in forms(lin.decl.protection, lin.decl.protections)
    if not key or not (source.name in lin.catalog.null_free or loose):
        return False
    # A row rule turns its hidden cells NULL: such a key no longer fixes the row.
    nulled = {
        c.lower()
        for r in lin.decl.row_rules
        if r.table.lower() == source.name.lower() and r.hide != "*"
        for c in r.hide
    }
    if any(k.lower() in nulled for k in key):
        return False
    grouped = {k.name for k in keys if isinstance(k, exp.Column) and k.table == col.table}
    return set(key) <= grouped


def _belongs_outside(agg: exp.Expr, lin: Lineage) -> bool:
    # SQLite gives an aggregate to the innermost query whose range variables its
    # argument names at any depth, queries nested in the argument excluded; with
    # none named it stays with the query holding it.
    inner = {id(q) for q in agg.find_all(exp.Query)}
    owners = {id(_owner(c, lin)) for c in agg.find_all(exp.Column) if c.table}
    owners -= {*inner, id(None)}
    return bool(owners) and id(holder(agg)) not in owners


def _names_alias(agg: exp.Expr) -> bool:
    # An aggregate always sits in a query; the empty fallback only satisfies typing.
    query = holder(agg)
    selects = branches(query) if query is not None else []
    outputs = {p.alias_or_name for s in selects for p in s.expressions if not is_star(p)}
    return any(not c.table and c.name in outputs for c in agg.find_all(exp.Column))


def _owner(col: exp.Column, lin: Lineage) -> exp.Expr | None:
    # The query whose FROM / JOIN range variable a qualified column names.
    scope = lin.owning_scope(col)
    return scope.expression if scope is not None else None
