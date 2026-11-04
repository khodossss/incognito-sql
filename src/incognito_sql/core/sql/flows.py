"""Every base column whose values may flow into a node, not only the most sensitive one.

`Lineage.ref_of` keeps one column per node (the most sensitive, the first on a tie);
a protection profile belongs to a column, so it must hold for each branch of a union.
"""

from sqlglot import exp
from sqlglot.optimizer.scope import Scope

from incognito_sql.core.config import ColumnClass
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.colref import ColumnRef
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.opaque import carries_nothing, is_window_key
from incognito_sql.core.sql.shape import (
    branches,
    holder,
    in_order,
    is_star,
    star_sources,
    visible_scopes,
)


def identifiers_in(lin: Lineage, node: exp.Expr) -> list[ColumnRef]:
    """Return every identifier column whose values may flow into `node`."""
    return [ref for ref in flows(lin, node) if ref.cls is ColumnClass.IDENTIFIER]


def identifiers_out(lin: Lineage, query: exp.Expr, index: int) -> list[ColumnRef]:
    """Return every identifier column behind the output at `index` of `query`."""
    return [ref for ref in outputs(lin, query, index) if ref.cls is ColumnClass.IDENTIFIER]


def flows(lin: Lineage, node: exp.Expr) -> list[ColumnRef]:
    """Return every base column whose values may flow into `node`."""
    found: list[ColumnRef] = []
    for sub in node.walk(prune=carries_nothing):
        if sub is not node and is_window_key(sub):  # a key inside the value, not the column
            continue
        if isinstance(sub, exp.Column) and not is_star(sub):
            found += _sources(lin, sub)
        elif isinstance(sub, exp.Subquery):
            found += outputs(lin, sub.this, index=0)
    return found


def outputs(lin: Lineage, query: exp.Expr, index: int) -> list[ColumnRef]:
    """Return every base column behind the output at `index`, over all branches."""
    found: list[ColumnRef] = []
    for select in branches(query):
        if index >= len(select.expressions) or is_star(select.expressions[index]):
            raise Rejection(Reason.UNKNOWN_COLUMN)
        found += flows(lin, select.expressions[index])
    return found


def _sources(lin: Lineage, col: exp.Column) -> list[ColumnRef]:
    query = holder(col)
    if query is None:
        raise Rejection(Reason.UNKNOWN_COLUMN)
    if not col.table:  # an unqualified ORDER BY name: every reading counts
        if not in_order(col, query):
            raise Rejection(Reason.UNKNOWN_COLUMN)
        readings = _find(lin, query, col.name) + [
            ref
            for seen in visible_scopes(lin.scope_of(query))
            for _, src in seen.selected_sources.values()
            for ref in _in_source(lin, src, col.name)
        ]
    else:
        found = lin.owning_scope(col)
        if found is None:
            raise Rejection(Reason.UNKNOWN_COLUMN)
        readings = _in_source(lin, found.selected_sources[col.table][1], col.name)
    if not readings:
        raise Rejection(Reason.UNKNOWN_COLUMN)
    return readings


def _in_source(lin: Lineage, source: exp.Table | Scope, name: str) -> list[ColumnRef]:
    if isinstance(source, Scope):
        return _find(lin, source.expression, name)
    ref = lin.in_source(source, name)
    return [] if ref is None else [ref]


def _find(lin: Lineage, query: exp.Expr, name: str) -> list[ColumnRef]:
    selects = branches(query)
    if len(selects) == 1:
        return _by_name(lin, selects[0], name)
    names = [p.alias_or_name for p in selects[0].expressions]
    return outputs(lin, query, names.index(name)) if names.count(name) == 1 else []


def _by_name(lin: Lineage, select: exp.Select, name: str) -> list[ColumnRef]:
    named = [p for p in select.expressions if not is_star(p) and p.alias_or_name == name]
    if len(named) > 1:
        raise Rejection(Reason.AMBIGUOUS_COLUMN)
    if named:
        return flows(lin, named[0])
    scope = lin.scope_of(select)
    found = [
        refs
        for star in select.expressions
        if is_star(star)
        for source in star_sources(star, scope)
        if (refs := _in_source(lin, source, name))
    ]
    if len(found) > 1:
        raise Rejection(Reason.AMBIGUOUS_COLUMN)
    return found[0] if found else []
