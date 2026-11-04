"""Default-deny check of AST node types, their arguments and system catalog names."""

from sqlglot import exp

from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.allowlist_table import ALLOWED_ARGS, ALLOWED_VALUES, FALSE_MEANINGFUL
from incognito_sql.core.sql.order_keys import is_tiebreak

__all__ = ["ALLOWED_ARGS", "ALLOWED_VALUES", "check_nodes"]

_SYSTEM_SCHEMAS = frozenset(
    {"pg_catalog", "information_schema", "performance_schema", "sys", "mysql"}
)
_SYSTEM_TABLES = _SYSTEM_SCHEMAS | {
    "sqlite_master",
    "sqlite_schema",
    "sqlite_temp_master",
    "dbstat",
}
_SYSTEM_PREFIXES = ("pg_", "duckdb_", "sqlite_", "pragma_")
# Unquoted names with these leading characters are bind markers in some dialect
# (SQLite parses `$x` as a column name but binds it as a parameter).
_BIND_MARKS = ("$", ":", "@", "?")


def check_nodes(tree: exp.Expression, *, allow_placeholders: bool = False) -> None:
    """Raise Rejection unless every node and every non-empty argument is allowed.

    System catalog tables are rejected first (SYSTEM_CATALOG); then any node type
    not in ALLOWED_ARGS (exact class), any non-empty argument outside its allowed
    set, or a disallowed shape is rejected (NODE_NOT_ALLOWED); a LIMIT / OFFSET /
    TOP must be a non-negative integer literal, parenthesized or not. Bind placeholders
    and an argument-free `RANDOM()` sort key are rejected unless
    `allow_placeholders` is set (for SQL the server rewrote).
    """
    # Only Expression nodes can be expanded; others are rejected by the second pass.
    for node in tree.walk(prune=lambda n: not isinstance(n, exp.Expression)):
        if isinstance(node, exp.Table) and _is_system(node):
            raise Rejection(Reason.SYSTEM_CATALOG)
    for node in tree.walk():
        if allow_placeholders and is_tiebreak(node):
            continue
        allowed = ALLOWED_ARGS.get(type(node))
        if allowed is None or not _shape_ok(node, allow_placeholders=allow_placeholders):
            raise Rejection(Reason.NODE_NOT_ALLOWED)
        for name, value in node.args.items():
            if _is_empty(type(node), name, value):
                continue
            if name not in allowed:
                raise Rejection(Reason.NODE_NOT_ALLOWED)
            values = ALLOWED_VALUES.get((type(node), name))
            if values is not None and str(value).upper() not in values:
                raise Rejection(Reason.NODE_NOT_ALLOWED)


def _shape_ok(node: exp.Expr, *, allow_placeholders: bool) -> bool:
    # Fetch is not in ALLOWED_ARGS (refused before this); its count is checked if it ever is.
    if isinstance(node, (exp.Limit, exp.Offset, exp.Fetch)):
        return _is_row_count(
            node.args.get("count" if isinstance(node, exp.Fetch) else "expression")
        )
    if isinstance(node, exp.Placeholder):
        return allow_placeholders
    if isinstance(node, exp.Identifier):
        return bool(node.args.get("quoted")) or not node.name.startswith(_BIND_MARKS)
    if isinstance(node, exp.Distinct):
        return len(node.expressions) <= 1
    if isinstance(node, exp.In):
        return bool(node.expressions) or node.args.get("query") is not None
    return not isinstance(node, exp.WindowSpec) or _fixed_frame(node, allow_placeholders)


def _fixed_frame(spec: exp.WindowSpec, allow_placeholders: bool) -> bool:  # noqa: FBT001
    # A frame bound is a fixed count or a keyword (CURRENT ROW, UNBOUNDED), never computed;
    # in SQL the server rewrote, the count travels as a bind placeholder.
    bounds = (spec.args.get("start"), spec.args.get("end"))
    return all(
        isinstance(b, str)
        or _is_row_count(b)
        or (allow_placeholders and isinstance(b, exp.Placeholder))
        for b in bounds
        if b is not None
    )


def _is_row_count(value: object) -> bool:
    # A row limit is a plain non-negative integer: anything computed (a subquery,
    # arithmetic) would turn a value into a row count.
    while isinstance(value, exp.Paren):
        value = value.this
    return isinstance(value, exp.Literal) and not value.is_string and value.name.isdigit()


def _is_system(table: exp.Table) -> bool:
    this = table.this
    name = this.name.lower() if isinstance(this, exp.Expr) else ""
    schema = table.db.lower()
    return name in _SYSTEM_TABLES or schema in _SYSTEM_SCHEMAS or name.startswith(_SYSTEM_PREFIXES)


def _is_empty(cls: type[exp.Expr], name: str, value: object) -> bool:
    # False counts as absent (sqlglot stores unset flags as False), except for the
    # args listed in FALSE_MEANINGFUL.
    if value is False:
        return (cls, name) not in FALSE_MEANINGFUL
    return value is None or (isinstance(value, list) and not value)
