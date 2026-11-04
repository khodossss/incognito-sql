"""Parse one read-only query and enforce the size limits."""

import sqlglot
from sqlglot import exp
from sqlglot.dialects.dialect import Dialect

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection

_LIMIT_BEFORE_OFFSET = frozenset({"sqlite", "mysql"})
_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)


def parse(sql: str, dialect: str, limits: Limits) -> exp.Expression:
    """Parse exactly one SELECT, WITH ... SELECT or set operation; raise Rejection otherwise.

    Enforces the SQL length (before parsing), AST node count, join count and
    IN-list length limits, and (SQLite, MySQL) refuses OFFSET without LIMIT. Node
    and argument checks are done by `check_nodes`.
    """
    if len(sql) > limits.max_sql_chars:
        raise Rejection(Reason.LIMIT_EXCEEDED)
    statements = _parse_all(sql, dialect)
    if not statements:
        raise Rejection(Reason.PARSE_ERROR)
    if len(statements) > 1:
        raise Rejection(Reason.MULTIPLE_STATEMENTS)
    tree = statements[0]
    if isinstance(tree, exp.Select | exp.SetOperation) and type(tree) in _ROOTS:
        _check_limits(tree, limits)
        _check_offsets(tree, dialect)
        _mark_double_quotes(tree, sql)
        return tree
    raise Rejection(Reason.NODE_NOT_ALLOWED)


def _parse_all(sql: str, dialect: str) -> list[exp.Expr] | None:
    reader = Dialect.get_or_raise(dialect)  # a bad dialect is a config error: let it raise
    # Any parser failure is swallowed here, so its message (it echoes SQL) is never
    # chained. sqlglot raises more than SqlglotError on odd input (AttributeError,
    # RecursionError).
    try:
        parsed = sqlglot.parse(sql, read=reader)
    except Exception:  # noqa: BLE001
        return None
    return [s for s in parsed if s is not None]


def _check_offsets(tree: exp.Expression, dialect: str) -> None:
    # SQLite and MySQL have no OFFSET without LIMIT (sqlglot would write SQLite's
    # `LIMIT -1`, which no row limit may be).
    if dialect not in _LIMIT_BEFORE_OFFSET:
        return
    for query in tree.find_all(exp.Select, exp.SetOperation):
        if query.args.get("offset") and not query.args.get("limit"):
            raise Rejection(Reason.NODE_NOT_ALLOWED)


def _check_limits(tree: exp.Expression, limits: Limits) -> None:
    nodes = joins = 0
    for node in tree.walk():
        nodes += 1
        if isinstance(node, exp.Join):
            joins += 1
        if isinstance(node, exp.In) and len(node.expressions) > limits.max_in_items:
            raise Rejection(Reason.LIMIT_EXCEEDED)
    if nodes > limits.max_ast_nodes or joins > limits.max_joins:
        raise Rejection(Reason.LIMIT_EXCEEDED)


DOUBLE_QUOTED = "double_quoted"


def _mark_double_quotes(tree: exp.Expression, sql: str) -> None:
    # sqlglot keeps no quote style; SQLite reads only a double-quoted name as a string
    # when it names nothing, so the style is noted from the text for that check.
    for ident in tree.find_all(exp.Identifier):
        start = ident.meta.get("start")
        if ident.args.get("quoted") and isinstance(start, int) and sql[start : start + 1] == '"':
            ident.meta[DOUBLE_QUOTED] = True
