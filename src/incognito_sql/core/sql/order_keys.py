"""Closed shapes for ORDER BY keys and for GROUP BY positions."""

from sqlglot import exp

from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.shape import branches, is_star

_VALUE_AGGREGATES = (exp.Sum, exp.Avg, exp.Min, exp.Max)


def check_order_keys(tree: exp.Expr, *, allow_rewrite: bool = False) -> None:
    """Refuse an ORDER BY key that is not a bare column, a position or a plain aggregate.

    With `allow_rewrite` (SQL the server rewrote), a bare `RANDOM()` key is accepted
    too: the random tiebreak the rewrite appends.

    A position (positive integer literal) is refused in a query with a star
    projection, since the star shifts positions; so is a GROUP BY position there.
    Runs on the tree as written and again on the qualified tree, because
    qualification resolves positions against the unexpanded projection list.
    Raises Rejection(NODE_NOT_ALLOWED).
    """
    for ordered in tree.find_all(exp.Ordered):
        if allow_rewrite and is_tiebreak(ordered.this):
            continue
        key = strip_parens(ordered.this)
        if (isinstance(key, exp.Column) and not is_star(key)) or _is_aggregate(key):
            continue
        order = ordered.parent
        if is_position(key) and not _has_star(order.parent if order is not None else None):
            continue
        raise Rejection(Reason.NODE_NOT_ALLOWED)
    for group in tree.find_all(exp.Group):
        keys = [strip_parens(k) for k in group.expressions]
        if any(isinstance(k, exp.Literal) for k in keys) and _has_star(group.parent):
            raise Rejection(Reason.NODE_NOT_ALLOWED)


def is_tiebreak(node: exp.Expr) -> bool:
    """Tell whether a node is an argument-free `RANDOM()` (`NEWID()`) standing as a sort key."""
    return (
        type(node) in {exp.Rand, exp.Uuid}
        and not any(node.args.values())
        and isinstance(node.parent, exp.Ordered)
        and node.arg_key == "this"
    )


def strip_parens(node: exp.Expr) -> exp.Expr:
    """Strip parentheses around an expression."""
    while isinstance(node, exp.Paren):
        node = node.this
    return node


def is_position(key: exp.Expr) -> bool:
    """Tell whether a sort key is a positive integer literal (an output position)."""
    return (
        isinstance(key, exp.Literal)
        and not key.is_string
        and key.name.isdigit()
        and int(key.name) > 0
    )


def _is_aggregate(key: exp.Expr) -> bool:
    arg = key.this if isinstance(key, (exp.Count, *_VALUE_AGGREGATES)) else None
    if isinstance(key, exp.Count):
        if isinstance(arg, exp.Star):
            return True  # bare COUNT(*) only; `COUNT(DISTINCT *)` falls through
        if isinstance(arg, exp.Distinct) and len(arg.expressions) == 1:
            arg = arg.expressions[0]
    return isinstance(arg, exp.Column) and not is_star(arg)


def _has_star(holder: exp.Expr | None) -> bool:
    if not isinstance(holder, (exp.Select, exp.SetOperation)):
        return False
    return any(is_star(p) for select in branches(holder) for p in select.expressions)
