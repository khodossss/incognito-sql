"""The allowed AST node types, their allowed arguments and closed argument values."""

from collections.abc import Mapping
from types import MappingProxyType

from sqlglot import exp

_LEFT_RIGHT = frozenset({"this", "expression"})
_THIS = frozenset({"this"})
_NONE: frozenset[str] = frozenset()
_SET_OPERATION = frozenset({"this", "expression", "distinct", "order", "limit", "offset", "with_"})

ALLOWED_ARGS: Mapping[type[exp.Expr], frozenset[str]] = MappingProxyType(
    {
        # query shape
        exp.Select: frozenset(
            {"expressions", "from_", "joins", "where", "group", "having"}
            | {"order", "limit", "offset", "distinct", "with_"}
        ),
        exp.Union: _SET_OPERATION,
        exp.Intersect: _SET_OPERATION,
        exp.Except: _SET_OPERATION,
        exp.With: frozenset({"expressions"}),
        exp.CTE: frozenset({"this", "alias"}),
        exp.Subquery: frozenset({"this", "alias"}),
        exp.From: _THIS,
        exp.Join: frozenset({"this", "on", "side", "kind"}),
        exp.Table: frozenset({"this", "db", "alias"}),
        exp.TableAlias: _THIS,
        exp.Where: _THIS,
        exp.Group: frozenset({"expressions"}),
        exp.Having: _THIS,
        exp.Order: frozenset({"expressions"}),
        exp.Ordered: frozenset({"this", "desc", "nulls_first"}),
        exp.Limit: frozenset({"expression"}),
        exp.Offset: frozenset({"expression"}),
        exp.Distinct: frozenset({"expressions"}),
        # names and atoms
        exp.Column: frozenset({"this", "table"}),
        exp.Identifier: frozenset({"this", "quoted"}),
        exp.Alias: frozenset({"this", "alias"}),
        exp.Star: _NONE,
        exp.Literal: frozenset({"this", "is_string"}),
        exp.Null: _NONE,
        exp.Boolean: _THIS,
        exp.Placeholder: _THIS,
        exp.Paren: _THIS,
        # predicates
        exp.EQ: _LEFT_RIGHT,
        exp.NEQ: _LEFT_RIGHT,
        exp.GT: _LEFT_RIGHT,
        exp.GTE: _LEFT_RIGHT,
        exp.LT: _LEFT_RIGHT,
        exp.LTE: _LEFT_RIGHT,
        exp.And: _LEFT_RIGHT,
        exp.Or: _LEFT_RIGHT,
        exp.Not: _THIS,
        exp.In: frozenset({"this", "expressions", "query"}),
        exp.Is: frozenset({"this", "expression", "negate"}),
        exp.Like: frozenset({"this", "expression", "negate"}),
        exp.ILike: frozenset({"this", "expression", "negate"}),
        exp.Between: frozenset({"this", "low", "high"}),
        exp.Exists: _THIS,
        # arithmetic and scalar functions
        exp.Add: _LEFT_RIGHT,
        exp.Sub: _LEFT_RIGHT,
        exp.Mul: _LEFT_RIGHT,
        exp.Div: frozenset({"this", "expression", "typed", "safe"}),
        exp.Neg: _THIS,
        exp.Case: frozenset({"this", "ifs", "default"}),
        exp.If: frozenset({"this", "true", "false"}),
        exp.Coalesce: frozenset({"this", "expressions", "is_nvl", "is_null"}),
        exp.Cast: frozenset({"this", "to"}),
        exp.DataType: frozenset({"this", "expressions"}),
        exp.DataTypeParam: _THIS,
        exp.Lower: _THIS,
        exp.Upper: _THIS,
        exp.Length: frozenset({"this", "binary"}),
        exp.Trim: _THIS,
        exp.Substring: frozenset({"this", "start", "length"}),
        exp.Round: frozenset({"this", "decimals"}),
        exp.Abs: _THIS,
        # dates and positions, over open columns (a function on an identifier is refused
        # by the policy whatever its name)
        exp.TimeToStr: frozenset({"this", "format"}),
        exp.TsOrDsToTimestamp: _THIS,
        exp.Date: frozenset({"this", "expressions"}),
        exp.StrPosition: frozenset({"this", "substr"}),
        exp.Anonymous: frozenset({"this", "expressions"}),
        # window functions: the policy admits them only where the profile does
        exp.Window: frozenset({"this", "partition_by", "order", "spec", "over"}),
        exp.WindowSpec: frozenset({"kind", "start", "start_side", "end", "end_side"}),
        exp.RowNumber: _NONE,
        exp.Rank: _NONE,
        exp.DenseRank: _NONE,
        # aggregates
        exp.Count: frozenset({"this", "big_int"}),
        exp.Sum: _THIS,
        exp.Avg: _THIS,
        exp.Min: _THIS,
        exp.Max: _THIS,
    }
)

# String-valued args whose values are closed too: only plain joins.
ALLOWED_VALUES: Mapping[tuple[type[exp.Expr], str], frozenset[str]] = MappingProxyType(
    {
        (exp.Join, "kind"): frozenset({"INNER", "OUTER", "CROSS"}),
        (exp.Join, "side"): frozenset({"LEFT", "RIGHT", "FULL"}),
        (exp.Window, "over"): frozenset({"OVER"}),
        (exp.WindowSpec, "kind"): frozenset({"ROWS", "RANGE"}),
        (exp.WindowSpec, "start_side"): frozenset({"PRECEDING", "FOLLOWING"}),
        (exp.WindowSpec, "end_side"): frozenset({"PRECEDING", "FOLLOWING"}),
        # Functions sqlglot does not model, by name: SQLite's date and time functions.
        (exp.Anonymous, "this"): frozenset({"JULIANDAY", "DATETIME", "TIME"}),
    }
)

# Unlisted args where False itself carries meaning (`Table.indexed=False` is SQLite
# NOT INDEXED): any value but None counts as present for these.
FALSE_MEANINGFUL: frozenset[tuple[type[exp.Expr], str]] = frozenset(
    {(exp.Table, "indexed"), (exp.DataType, "nullable")}
)
