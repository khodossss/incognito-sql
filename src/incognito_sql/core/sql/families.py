"""Cast-safe type groups of values in a qualified query, through every set-operation branch."""

from collections.abc import Sequence

from sqlglot import exp
from sqlglot.optimizer.scope import Scope

from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.shape import branches, is_star, unwrap
from incognito_sql.core.sql.typefamily import cast_group


def value_families(node: exp.Expr, lin: Lineage, catalog: Catalog) -> set[str]:
    """Return the cast-safe groups a value may come from: one per base column it traces to.

    A derived or set-operation source contributes every branch; NULL contributes
    none; a value that is not a column traces to its most sensitive column.
    """
    node = unwrap(node) if isinstance(node, exp.Subquery) else _strip(node)
    if isinstance(node, exp.Null):
        return set()
    projections: list[exp.Expr] | None = None
    if isinstance(node, exp.Column) and node.table:
        scope = lin.owning_scope(node)
        source = scope.selected_sources[node.table][1] if scope is not None else None
        if isinstance(source, Scope):
            projections = _projections(source.expression, name=node.name)
    elif isinstance(node, exp.Select | exp.SetOperation):
        projections = _projections(node, index=0)
    if projections is not None:
        return set().union(*(value_families(p, lin, catalog) for p in projections))
    ref = lin.ref_of(node)
    return {cast_group(catalog.columns.get(ref.table, {}).get(ref.column, ""))}


def one_family(families: Sequence[set[str]]) -> bool:
    """Tell whether values of these groups can meet with no cast that fails on some values."""
    found = set().union(*families)
    typed = [f for f in families if f]
    return len(found) <= 1 and not ("" in found and len(typed) > 1)


def _strip(node: exp.Expr) -> exp.Expr:
    while isinstance(node, (exp.Paren, exp.Alias)):
        node = node.this
    return node


def _projections(query: exp.Expr, *, name: str = "", index: int = -1) -> list[exp.Expr] | None:
    selects = branches(query)
    if index < 0:
        names = [p.alias_or_name for p in selects[0].expressions]
        if names.count(name) != 1:
            return None
        index = names.index(name)
    # Second layer: Lineage._at refused these when the caller traced the value (ref_of).
    if any(index >= len(s.expressions) or is_star(s.expressions[index]) for s in selects):
        return None
    return [s.expressions[index] for s in selects]
