"""Nodes through which no value of the columns inside them reaches the value outside."""

from sqlglot import exp

# Nodes whose value carries no value of the columns inside them (a count, a truth value,
# a length).
OPAQUE = (exp.Count, exp.Predicate, exp.Connector, exp.Not, exp.Subquery, exp.Length)


def carries_nothing(node: exp.Expr) -> bool:
    """Tell whether no value under `node` flows into the value that contains it.

    An opaque node, and a window key (see `is_window_key`).
    """
    return isinstance(node, OPAQUE) or is_window_key(node)


def is_window_key(node: exp.Expr) -> bool:
    """Tell whether `node` is a window's sort or partition key.

    The key orders or splits the rows; the window's value comes from its function.
    """
    return isinstance(node.parent, exp.Window) and node.arg_key in ("order", "partition_by")
