"""Structural policy checks: stars, hidden mentions, set operations, ORDER BY positions."""

from sqlglot import exp
from sqlglot.optimizer.scope import Scope

from incognito_sql.core.config import ColumnClass, Operation, column_operations
from incognito_sql.core.config.forms import Form, forms
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.aggregates import check_sums
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.colref import HIDDEN_RANK, rank
from incognito_sql.core.sql.families import one_family, value_families
from incognito_sql.core.sql.flows import identifiers_in, identifiers_out
from incognito_sql.core.sql.grouping import check_grouping
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.order_keys import check_order_keys, is_position, strip_parens
from incognito_sql.core.sql.row_mask import check_dropped_rows
from incognito_sql.core.sql.scan_order import check_scan_order
from incognito_sql.core.sql.shape import branches, is_star, star_sources, unwrap
from incognito_sql.core.sql.stars import check_star_places


def check_mentions(
    tree: exp.Expr, lin: Lineage, catalog: Catalog, *, allow_rewrite: bool = False
) -> None:
    """Check sort keys, stars, sums, grouping, hidden columns, set operations, positions.

    `allow_rewrite` admits the random sort key of SQL the server rewrote.
    """
    if tree.find(exp.Window) is not None and Form.WINDOW not in forms(
        lin.decl.protection, lin.decl.protections
    ):
        raise Rejection(Reason.NODE_NOT_ALLOWED)
    check_star_places(tree)
    check_order_keys(tree, allow_rewrite=allow_rewrite)
    check_sums(tree, lin)
    check_grouping(tree, lin)
    check_dropped_rows(tree, lin, catalog)
    for select in tree.find_all(exp.Select):
        _check_stars(select, lin)
    for col in tree.find_all(exp.Column):
        if not is_star(col) and rank(lin.source_of(col).cls) == HIDDEN_RANK:
            raise Rejection(Reason.HIDDEN_COLUMN)
    for union in tree.find_all(exp.SetOperation):
        _check_union(union, lin, catalog)
    for ordered in tree.find_all(exp.Ordered):
        _check_ordinal(ordered, lin)
    for window in tree.find_all(exp.Window):
        _check_frame(window, lin)
    check_scan_order(tree, lin, catalog)


def _check_union(union: exp.SetOperation, lin: Lineage, catalog: Catalog) -> None:
    # A set operation compares its rows: an identifier position takes only
    # identifiers (or NULL) of one type family from every branch (across families
    # the DBMS casts, and a cast that fails on some values only is a channel).
    # Stars cannot be checked by position.
    selects = branches(union)
    if any(is_star(p) for s in selects for p in s.expressions):
        raise Rejection(Reason.UNKNOWN_COLUMN)
    for i in range(min(len(s.expressions) for s in selects)):
        projections = [s.expressions[i] for s in selects]
        refs = [lin.ref_of(p) for p in projections]
        if all(ref.cls is not ColumnClass.IDENTIFIER for ref in refs):
            continue
        for proj, ref in zip(projections, refs, strict=True):
            if ref.cls is not ColumnClass.IDENTIFIER and not isinstance(unwrap(proj), exp.Null):
                raise Rejection(Reason.PII_JOIN_WITH_OPEN)
        if not one_family([value_families(p, lin, catalog) for p in projections]):
            raise Rejection(Reason.LITERAL_TYPE_MISMATCH)
        # INTERSECT / EXCEPT match identifiers against identifiers: a join of them.
        if not isinstance(union, exp.Union) and not all(
            Operation.JOIN_IDENT in column_operations(lin.decl, ref.table, ref.column)
            for p in projections
            for ref in identifiers_in(lin, p)
        ):
            raise Rejection(Reason.PII_OPERATION)


def _check_frame(window: exp.Window, lin: Lineage) -> None:
    # A RANGE frame with an offset holds the rows within a distance of the sort key: over
    # an identifier key its counts measure the distance between values, more than their
    # order. ROWS / GROUPS count positions, as the ranking functions do.
    spec, order = window.args.get("spec"), window.args.get("order")
    if spec is None or order is None or str(spec.args.get("kind", "")).upper() != "RANGE":
        return
    bounds = (spec.args.get("start"), spec.args.get("end"))
    if all(b is None or isinstance(b, str) for b in bounds):
        return
    if any(identifiers_in(lin, key.this) for key in order.expressions):
        raise Rejection(Reason.PII_OPERATION)


def _check_stars(select: exp.Select, lin: Lineage) -> None:
    # Star expansion is classified per base column downstream; a derived source
    # would hide its lineage there.
    stars = [p for p in select.expressions if is_star(p)]
    if not stars:
        return
    scope = lin.scope_of(select)
    for star in stars:
        sources = star_sources(star, scope)
        if not sources:
            raise Rejection(Reason.UNKNOWN_COLUMN)
        if any(isinstance(source, Scope) for source in sources):
            raise Rejection(Reason.NODE_NOT_ALLOWED)


def _check_ordinal(ordered: exp.Ordered, lin: Lineage) -> None:
    # `ORDER BY (1)` is a position too (qualify rewrites only a bare `1`).
    key = strip_parens(ordered.this)
    order = ordered.parent
    holder = order.parent if isinstance(order, exp.Order) else None
    if not isinstance(holder, (exp.Select, exp.SetOperation)) or not is_position(key):
        return
    behind = identifiers_out(lin, holder, int(key.name) - 1)
    if not all(
        Operation.ORDER in column_operations(lin.decl, ref.table, ref.column) for ref in behind
    ):
        raise Rejection(Reason.PII_OPERATION)
