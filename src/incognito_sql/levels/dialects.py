"""Writing a question in the database's dialect so that it asks the same thing there.

SQL Server's ``LEN`` drops trailing spaces: the length of a value is written there as
``LEN(CONCAT(value, 'x')) - 1``, ``CONCAT`` taking any type as text. ``LIKE`` ignores
case in SQLite (ASCII), as the questions mean it; PostgreSQL and DuckDB ask ``ILIKE``.
"""

import sqlglot
from sqlglot import exp

_MARK = "x"


def _length(node: exp.Expr) -> exp.Expr:
    if not isinstance(node, exp.Length) or isinstance(node.this, exp.Anonymous):
        return node
    padded = exp.Anonymous(this="CONCAT", expressions=[node.this.copy(), exp.Literal.string(_MARK)])
    return exp.paren(exp.Length(this=padded) - 1)


def _ilike(node: exp.Expr) -> exp.Expr:
    if isinstance(node, exp.Like):
        return exp.ILike(this=node.this.copy(), expression=node.expression.copy())
    return node


def written(tree: exp.Expr, dialect: str) -> str:
    """Return ``tree`` as SQL of ``dialect``."""
    if dialect == "tsql":
        tree = tree.transform(_length)
    if dialect in {"postgres", "duckdb"}:
        tree = tree.transform(_ilike)
    return tree.sql(dialect=dialect)


def translated(sql: str, dialect: str) -> str:
    """Return SQLite ``sql`` as SQL of ``dialect``."""
    if dialect == "sqlite":
        return sql
    return written(sqlglot.parse_one(sql, read="sqlite"), dialect)
