"""Row rules: cells of a table the model never sees, in the rows a condition names."""

from collections.abc import Mapping
from typing import Literal

import sqlglot
from pydantic import BaseModel, ConfigDict
from sqlglot import exp
from sqlglot.errors import ParseError

# A condition reads only what the model may see of its row: the pattern of hidden cells
# shows where it holds.
READABLE = frozenset({"open", "quasi"})
# A rule hides what the model would otherwise see; describe names those columns.
HIDABLE = frozenset({"open", "quasi", "identifier"})
_NODES = (
    exp.Column,
    exp.Identifier,
    exp.Literal,
    exp.Boolean,
    exp.Null,
    exp.Paren,
    exp.Neg,
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.And,
    exp.Or,
    exp.Not,
    exp.In,
    exp.Is,
    exp.Like,
    exp.ILike,
    exp.Between,
)
_CONDITIONS = (
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.And,
    exp.Or,
    exp.Not,
    exp.In,
    exp.Is,
    exp.Like,
    exp.ILike,
    exp.Between,
    exp.Paren,
    exp.Boolean,
)


class RowRule(BaseModel):
    """Where ``where`` holds (or is unknown), the ``hide`` columns are NULL; ``*`` drops the row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    table: str
    hide: list[str] | Literal["*"]
    where: str


def rule_problem(
    rule: RowRule, classes: Mapping[str, Mapping[str, str]], dialect: str
) -> str | None:
    """Return what is wrong with a rule against the declared columns, or None."""
    table = rule.table.lower()
    columns = classes.get(table)
    if columns is None:
        return f"row rule on {rule.table}: the table is not declared"
    if rule.hide != "*":
        unknown = [c for c in rule.hide if columns.get(c.lower()) not in HIDABLE]
        if unknown or not rule.hide:
            return f"row rule on {rule.table}: hide names no column the model sees"
    problem = _condition_problem(rule, columns, dialect)
    return f"row rule on {rule.table}: {problem}" if problem is not None else None


def _condition_problem(rule: RowRule, columns: Mapping[str, str], dialect: str) -> str | None:
    try:
        tree = condition(rule, dialect)
    except ParseError:
        return "the condition does not parse"
    if not isinstance(tree, _CONDITIONS) or any(not isinstance(n, _NODES) for n in tree.walk()):
        return "the condition is not a plain comparison"
    for col in tree.find_all(exp.Column):
        if col.table and col.table.lower() != rule.table.lower():
            return "the condition reads another table"
        if columns.get(col.name.lower()) not in READABLE:
            return "the condition reads a column that is not open"
    return None


def condition(rule: RowRule, dialect: str) -> exp.Expr:
    """Parse the condition of a rule in the database's dialect."""
    return sqlglot.parse_one(rule.where, read=dialect)


def rules_problem(rules: list[RowRule], dialect: str) -> str | None:
    """Return a rule whose condition reads a column another rule of the table hides, or None.

    The NULLs one rule leaves show where its condition holds: over a hidden cell they
    would show that cell.
    """
    hidden: dict[str, set[str]] = {}
    for rule in rules:
        if rule.hide != "*":
            hidden.setdefault(rule.table.lower(), set()).update(c.lower() for c in rule.hide)
    for rule in rules:
        read = {c.name.lower() for c in condition(rule, dialect).find_all(exp.Column)}
        if read & hidden.get(rule.table.lower(), set()):
            return f"row rule on {rule.table}: the condition reads a column a row rule hides"
    return None
