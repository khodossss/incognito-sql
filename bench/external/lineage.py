"""Which answer columns of a reference query show a hidden column, and is it ordered.

An answer column is *opaque* when it is a hidden column itself (through aliases,
derived tables and CTEs), or ``MIN``/``MAX`` of one: the reference holds the value, a
protecting tool may show a token or a pseudonym instead. In a set operation a column is
opaque when it is in any branch. A query is ordered when its outermost query has
``ORDER BY``. A query sqlglot cannot read has no opaque column and is not ordered.
"""

from collections.abc import Set as AbstractSet

from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, build_scope

Hidden = AbstractSet[tuple[str, str]]


def shape(
    sql: str, schema: dict[str, dict[str, str]], hidden: Hidden
) -> tuple[frozenset[int], bool]:
    """Return the opaque answer columns of ``sql`` and whether its order is part of it."""
    try:
        tables: dict[str, object] = {t: dict(cols) for t, cols in schema.items()}
        tree = qualify(
            parse_one(sql, read="sqlite"),
            schema=tables,
            dialect="sqlite",
            validate_qualify_columns=False,
        )
        root = build_scope(tree)
    except (SqlglotError, KeyError, ValueError, AttributeError):
        return frozenset(), False
    if root is None:
        return frozenset(), False
    ordered = isinstance(tree, exp.Query) and tree.args.get("order") is not None
    opaque = {
        i
        for branch in _branches(root)
        for i, column in enumerate(_selects(branch))
        if _origin(branch, column, 0) in hidden
    }
    return frozenset(opaque), ordered


def _branches(scope: Scope) -> list[Scope]:
    if scope.set_operation_scopes:
        return [b for s in scope.set_operation_scopes for b in _branches(s)]
    return [scope] if isinstance(scope.expression, exp.Select) else []


def _selects(scope: Scope) -> list[exp.Expr]:
    expression = scope.expression
    return list(expression.selects) if isinstance(expression, exp.Select) else []


def _origin(scope: Scope, node: exp.Expr, depth: int) -> tuple[str, str] | None:
    """Return (table, column) a select expression shows unchanged, lower-cased."""
    node = node.unalias()
    if isinstance(node, exp.Min | exp.Max) and isinstance(node.this, exp.Column):
        node = node.this
    if not isinstance(node, exp.Column) or depth > 8:  # noqa: PLR2004 -- nesting bound
        return None
    source = scope.sources.get(node.table)
    if isinstance(source, exp.Table):
        return source.name.lower(), node.name.lower()
    if isinstance(source, Scope):
        for inner in _branches(source):
            for select in _selects(inner):
                if select.alias_or_name.lower() == node.name.lower():
                    return _origin(inner, select, depth + 1)
    return None
