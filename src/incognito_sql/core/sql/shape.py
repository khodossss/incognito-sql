"""Shape helpers over sqlglot query trees."""

from sqlglot import exp
from sqlglot.optimizer.scope import Scope

from incognito_sql.core.errors import Reason, Rejection


def is_star(node: exp.Expr) -> bool:
    """Tell whether a projection is `*` or `t.*`."""
    return isinstance(node, exp.Star) or (
        isinstance(node, exp.Column) and isinstance(node.this, exp.Star)
    )


def unwrap(node: exp.Expr) -> exp.Expr:
    """Strip parentheses, aliases and subquery wrappers around a query or value."""
    while isinstance(node, (exp.Paren, exp.Alias, exp.Subquery)):
        node = node.this
    return node


def holder(node: exp.Expr) -> exp.Expr | None:
    """Return the nearest SELECT or set operation that contains `node`."""
    found = node.parent
    while found is not None and not isinstance(found, exp.Query):
        found = found.parent
    return found


def branches(query: exp.Expr) -> list[exp.Select]:
    """List the SELECT branches of a query, left to right (one for a plain SELECT)."""
    query = unwrap(query)
    if isinstance(query, exp.SetOperation):
        return [*branches(query.left), *branches(query.right)]
    if isinstance(query, exp.Select):
        return [query]
    raise Rejection(Reason.UNKNOWN_COLUMN)


def in_order(node: exp.Expr, holder: exp.Expr) -> bool:
    """Tell whether `node` sits in the ORDER BY of `holder`."""
    while node.parent is not holder and node.parent is not None:
        node = node.parent
    return node is holder.args.get("order")


def visible_scopes(scope: Scope) -> list[Scope]:
    """List `scope` and the enclosing scopes whose FROM sources its SQL can see.

    An ancestor is visible once the walk outward has crossed at least one
    subquery boundary (scalar, IN, EXISTS): such a subquery correlates with its
    outer query, and so does every derived table or CTE body nested inside it.
    Crossing only derived-table or CTE boundaries makes nothing visible.
    """
    seen = [scope]
    crossed = False
    while scope.parent is not None:
        crossed = crossed or scope.is_subquery
        scope = scope.parent
        if crossed:
            seen.append(scope)
    return seen


def star_sources(star: exp.Expr, scope: Scope) -> list[exp.Table | Scope]:
    """List the FROM / JOIN sources a `*` or `t.*` projection of `scope` expands."""
    # selected_sources holds only range variables; `sources` also lists visible CTEs.
    if isinstance(star, exp.Column):
        selected = scope.selected_sources.get(star.table)
        return [selected[1]] if selected is not None else []
    return [source for _, source in scope.selected_sources.values()]
