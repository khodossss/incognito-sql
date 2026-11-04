"""Column lineage: which base column a value in a qualified query comes from."""

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from incognito_sql.core.config import Declaration, column_class
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.colref import COMPUTED, ColumnRef, rank
from incognito_sql.core.sql.opaque import carries_nothing, is_window_key
from incognito_sql.core.sql.shape import (
    branches,
    holder,
    in_order,
    is_star,
    star_sources,
    visible_scopes,
)


class Lineage:
    """Resolves columns of one qualified tree to base columns of the catalog."""

    def __init__(self, tree: exp.Expr, catalog: Catalog, decl: Declaration) -> None:
        """Index the scopes of `tree`."""
        self._scopes = {id(s.expression): s for s in traverse_scope(tree)}
        self._catalog = catalog
        self._decl = decl

    @property
    def catalog(self) -> Catalog:
        """The catalog the columns resolve against."""
        return self._catalog

    @property
    def decl(self) -> Declaration:
        """The declaration whose classes the columns carry."""
        return self._decl

    def source_of(self, col: exp.Column) -> ColumnRef:
        """Return the base column behind `col`; untraceable -> Rejection(UNKNOWN_COLUMN)."""
        query = holder(col)
        scope = self._scopes.get(id(query))
        if query is None or scope is None:
            raise Rejection(Reason.UNKNOWN_COLUMN)
        if not col.table:
            return self._order_name(col, query, scope)
        found = self.owning_scope(col)
        if found is None:
            raise Rejection(Reason.UNKNOWN_COLUMN)
        ref = self.in_source(found.selected_sources[col.table][1], col.name)
        if ref is None:
            raise Rejection(Reason.UNKNOWN_COLUMN)
        return ref

    def owning_scope(self, col: exp.Column) -> Scope | None:
        """Return the scope whose FROM / JOIN range variable a qualified column names."""
        # The qualifier names a range variable of this or an outer query; a CTE
        # of the same name that is not in FROM does not hide it.
        found = self._scopes.get(id(holder(col)))
        while found is not None and col.table not in found.selected_sources:
            found = found.parent
        return found

    def scope_of(self, query: exp.Expr) -> Scope:
        """Return the scope of a SELECT or set operation of the tree."""
        scope = self._scopes.get(id(query))
        if scope is None:  # a query outside sqlglot's scopes (none known); narrows the type
            raise Rejection(Reason.UNKNOWN_COLUMN)
        return scope

    def _order_name(self, col: exp.Column, holder: exp.Expr, scope: Scope) -> ColumnRef:
        # An unqualified name left by qualify sits in ORDER BY. Databases differ on
        # whether it means the output alias or an input column (nested in an
        # expression it is an input column, of this or an enclosing query), so
        # every reading counts: the most sensitive wins; none -> untraceable.
        if not in_order(col, holder):
            raise Rejection(Reason.UNKNOWN_COLUMN)
        readings = [self._find(holder, col.name)]
        readings += [
            self.in_source(src, col.name)
            for seen in visible_scopes(scope)
            for _, src in seen.selected_sources.values()
        ]
        found = [ref for ref in readings if ref is not None]
        if not found:
            raise Rejection(Reason.UNKNOWN_COLUMN)
        return max(found, key=lambda r: rank(r.cls))

    def ref_of(self, node: exp.Expr) -> ColumnRef:
        """Return the most sensitive column whose values may flow into `node`."""
        best = COMPUTED
        for sub in node.walk(prune=carries_nothing):
            if sub is not node and is_window_key(sub):  # a key inside the value, not the column
                continue
            if isinstance(sub, exp.Column) and not is_star(sub):
                ref = self.source_of(sub)
            elif isinstance(sub, exp.Subquery):
                ref = self.output(sub.this, index=0)
            else:
                continue
            if rank(ref.cls) > rank(best.cls):
                best = ref
        return best

    def output(self, query: exp.Expr, *, index: int) -> ColumnRef:
        """Return the output column of `query` at a 0-based position; else Rejection."""
        refs = [self._at(select, index) for select in branches(query)]
        return max(refs, key=lambda r: rank(r.cls))

    def _find(self, query: exp.Expr, name: str) -> ColumnRef | None:
        selects = branches(query)
        if len(selects) == 1:
            return self._by_name(selects[0], name)
        names = [p.alias_or_name for p in selects[0].expressions]
        if names.count(name) != 1:
            return None
        return self.output(query, index=names.index(name))

    def _at(self, select: exp.Select, index: int) -> ColumnRef:
        if index >= len(select.expressions) or is_star(select.expressions[index]):
            raise Rejection(Reason.UNKNOWN_COLUMN)
        return self.ref_of(select.expressions[index])

    def _by_name(self, select: exp.Select, name: str) -> ColumnRef | None:
        named = [p for p in select.expressions if not is_star(p) and p.alias_or_name == name]
        if len(named) > 1:
            raise Rejection(Reason.AMBIGUOUS_COLUMN)
        if named:
            return self.ref_of(named[0])
        scope = self.scope_of(select)
        found = [
            ref
            for star in select.expressions
            if is_star(star)
            for source in star_sources(star, scope)
            if (ref := self.in_source(source, name)) is not None
        ]
        if len(found) > 1:
            raise Rejection(Reason.AMBIGUOUS_COLUMN)
        return found[0] if found else None

    def in_source(self, source: exp.Table | Scope, name: str) -> ColumnRef | None:
        """Return the column `name` of a range variable's source, or None."""
        if isinstance(source, Scope):
            return self._find(source.expression, name)
        if name not in self._catalog.columns.get(source.name, {}):
            return None
        return ColumnRef(source.name, name, column_class(self._decl, source.name, name))
