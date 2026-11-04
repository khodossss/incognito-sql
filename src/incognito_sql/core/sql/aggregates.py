"""SUM and AVG: over a stored column, a bounded CASE, or what the profile admits."""

from sqlglot import exp
from sqlglot.optimizer.scope import Scope

from incognito_sql.core.config.forms import Form, forms
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.order_keys import strip_parens
from incognito_sql.core.sql.shape import branches, is_star, star_sources


def check_sums(tree: exp.Expr, lin: Lineage) -> None:
    """Refuse SUM / AVG of anything but a column stored in a table.

    The argument (optionally DISTINCT) must be a column that reaches a table
    column through bare column references only, across derived tables, CTEs and
    set operations. A crafted value can overflow (float to infinity, integer to
    an error) at a point that depends on the order rows are added, which may
    follow an index on a personal column. A CASE whose every result is a small
    integer literal or NULL cannot overflow and adds up exactly in any order: it
    is allowed too; any other computed value only where the database's profile
    admits that form. Raises Rejection(NODE_NOT_ALLOWED).
    """
    computed = Form.COMPUTED_SUM in forms(lin.decl.protection, lin.decl.protections)
    for agg in tree.find_all(exp.Sum, exp.Avg):
        arg = strip_parens(agg.this)
        if isinstance(arg, exp.Distinct) and len(arg.expressions) == 1:
            arg = strip_parens(arg.expressions[0])
        if not (computed or _stored(arg, lin) or _counted(arg)):
            raise Rejection(Reason.NODE_NOT_ALLOWED)


_SMALL = 10**6


def _counted(node: exp.Expr) -> bool:
    # CASE ... THEN 1 ELSE 0 END and the like: every result a small non-negative integer or NULL.
    if isinstance(node, exp.Case):
        results = [i.args.get("true") for i in node.args.get("ifs") or []]
        results.append(node.args.get("default"))
    elif isinstance(node, exp.If):
        results = [node.args.get("true"), node.args.get("false")]
    else:
        return False
    return all(_small(strip_parens(r)) if r is not None else True for r in results)


def _small(node: exp.Expr) -> bool:
    # A bind placeholder reaches here only in SQL the server rewrote (the model's are
    # refused before): it carries a literal this check already admitted.
    if isinstance(node, exp.Null | exp.Placeholder):
        return True
    # Non-negative only: with mixed signs a running total could pass a type's limit
    # midway on one row order and not on another.
    return (
        isinstance(node, exp.Literal)
        and not node.is_string
        and node.name.isdigit()
        and int(node.name) <= _SMALL
    )


def _stored(node: exp.Expr | None, lin: Lineage) -> bool:
    if not isinstance(node, exp.Column) or is_star(node) or not node.table:
        return False
    scope = lin.owning_scope(node)
    if scope is None:
        return False
    return _stored_in(scope.selected_sources[node.table][1], node.name, lin)


def _stored_in(source: exp.Table | Scope, name: str, lin: Lineage) -> bool:
    if isinstance(source, exp.Table):
        return lin.in_source(source, name) is not None
    selects = branches(source.expression)
    if len(selects) > 1:  # a set operation: the same position in every branch
        names = [p.alias_or_name for p in selects[0].expressions]
        if names.count(name) != 1:
            return False
        index = names.index(name)
        return all(_stored(_bare(s.expressions[index:][:1]), lin) for s in selects)
    select = selects[0]
    named = [p for p in select.expressions if not is_star(p) and p.alias_or_name == name]
    if named:
        return len(named) == 1 and _stored(_bare(named), lin)
    found = [
        src
        for star in select.expressions
        if is_star(star)
        for src in star_sources(star, lin.scope_of(select))
        if lin.in_source(src, name) is not None
    ]
    return len(found) == 1 and _stored_in(found[0], name, lin)


def _bare(projections: list[exp.Expr]) -> exp.Expr | None:
    # The value of a one-item projection list, alias and parentheses removed.
    if len(projections) != 1:
        return None
    node = projections[0]
    return strip_parens(node.this if isinstance(node, exp.Alias) else node)
