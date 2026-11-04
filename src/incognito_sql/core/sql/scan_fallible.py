"""Errors some rows raise, where a query may stop at its first matching row."""

from sqlglot import exp

from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.constants import safe_constant
from incognito_sql.core.sql.flows import flows
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.scan_spellings import own
from incognito_sql.core.sql.typefamily import NUMBER, TEXT, literal_kind

# Nodes whose evaluation can fail on some values: an overflow, a division by zero, a cast
# or a date that does not parse, a negative substring length.
_FALLIBLE = (
    exp.Add,
    exp.Sub,
    exp.Mul,
    exp.Div,
    exp.Neg,
    exp.Cast,
    exp.Round,
    exp.Abs,
    exp.Substring,
    exp.TimeToStr,
    exp.TsOrDsToTimestamp,
    exp.Date,
    exp.Sum,
    exp.Avg,
)
# Nodes that meet values of two types: SQL Server and DuckDB convert a text column to a
# number row by row, and fail on a row that holds no number.
_MEETINGS = (
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.Between,
    exp.In,
    exp.Case,
    exp.If,
    exp.Coalesce,
)
_CONVERTS = frozenset({"tsql", "duckdb"})
# Where a constant is evaluated or not depending on the row.
_CONDITIONAL = (exp.Case, exp.If, exp.Coalesce, exp.Nullif, exp.And, exp.Or)
_TEXT_FUNCS = (exp.Lower, exp.Upper, exp.Trim, exp.Substring)
_NULL = "null"
# A subquery under these is a row source the outer query reads whole.
_SOURCES = (exp.From, exp.Join, exp.SetOperation)


def check_fallible(tree: exp.Expr, lin: Lineage, catalog: Catalog) -> None:
    """Refuse an expression some rows make fail where the query may stop at its first row.

    Whether it fails then tells which row the scan met first. A constant fails or not
    whatever the rows.
    """
    for node in fallible(tree, lin, catalog):
        if _may_stop_early(node):
            raise Rejection(Reason.FALLIBLE_SUBQUERY)


def fallible(
    tree: exp.Expr, lin: Lineage, catalog: Catalog, *, every_constant: bool = False
) -> list[exp.Expr]:
    """Return each node that can fail on some rows.

    It reads a column, or it is a constant that may fail and is evaluated only on some
    rows: a branch of CASE / IIF / COALESCE / NULLIF, or a side of AND / OR, which a DBMS
    may skip. With ``every_constant`` any constant that may fail counts: whether it is
    evaluated at all can depend on which rows reach it.
    """
    converts = lin.decl.dialect in _CONVERTS
    return [
        node
        for node in tree.find_all(*_FALLIBLE, *_MEETINGS)
        if (not isinstance(node, _MEETINGS) or (converts and _converts(node, lin, catalog)))
        and (node.find(exp.Column) is not None or _risky_constant(node, every=every_constant))
    ]


def _risky_constant(node: exp.Expr, *, every: bool) -> bool:
    # A bind placeholder is the server's own: a literal whose type was checked before.
    if node.find(exp.Placeholder) is not None or safe_constant(node):
        return False
    return every or node.find_ancestor(*_CONDITIONAL) is not None


def _may_stop_early(node: exp.Expr) -> bool:
    # Up to the root: a query that reads all its input evaluates the node for every row it
    # reads, unless a boundary above may stop reading that query itself early.
    whole = False
    up = node.parent
    while up is not None:
        if isinstance(up, exp.Select):
            whole = _reads_whole(up)
        elif isinstance(up, exp.SetOperation):
            whole = False
        elif _may_stop(up) and not whole:
            return True
        up = up.parent
    return False


def _may_stop(node: exp.Expr) -> bool:
    # EXISTS, IN (SELECT ...), a scalar subquery and a WITH query read until they have
    # what they need.
    if isinstance(node, exp.Exists | exp.CTE):
        return True
    return isinstance(node, exp.Subquery) and not isinstance(node.parent, _SOURCES)


def _reads_whole(select: exp.Select) -> bool:
    # One row out of all its input: no FROM, or an aggregate without GROUP BY.
    if select.args.get("from_") is None:
        return True
    return select.args.get("group") is None and any(
        own(select, agg) for agg in select.find_all(exp.AggFunc)
    )


def _converts(node: exp.Expr, lin: Lineage, catalog: Catalog) -> bool:
    # A text column meets anything not known to be text: a number, a boolean, a date, or
    # a value whose type is not plain to see (a negated or computed one, a subquery).
    kinds = [(_kind(op, lin, catalog), op) for op in _operands(node)]
    text_column = any(k == TEXT and op.find(exp.Column) is not None for k, op in kinds)
    return text_column and any(k not in {TEXT, _NULL} for k, _ in kinds)


def _operands(node: exp.Expr) -> list[exp.Expr]:
    if isinstance(node, exp.Case):
        found = [i.args.get("true") for i in node.args.get("ifs") or []]
        return [o for o in [*found, node.args.get("default")] if o is not None]
    if isinstance(node, exp.If):
        return [o for o in (node.args.get("true"), node.args.get("false")) if o is not None]
    if isinstance(node, exp.Between):
        return [node.this, node.args["low"], node.args["high"]]
    if isinstance(node, exp.In):
        query = node.args.get("query")
        return [node.this, *node.expressions, *([query] if query is not None else [])]
    if isinstance(node, exp.Coalesce):
        return [node.this, *node.expressions]
    return [node.this, node.args["expression"]]


def _kind(node: exp.Expr, lin: Lineage, catalog: Catalog) -> str | None:
    # TEXT, NUMBER, _NULL, or None when the type is not plain to see.
    while isinstance(node, exp.Paren | exp.Alias):
        node = node.this
    if isinstance(node, exp.Null):
        return _NULL
    if isinstance(node, exp.Literal):
        return TEXT if node.is_string else NUMBER
    if isinstance(node, _TEXT_FUNCS):
        return TEXT
    if isinstance(node, exp.Subquery) and isinstance(node.this, exp.Select):
        return _kind(node.this.expressions[0], lin, catalog)
    return _column_kind(node, lin, catalog) if isinstance(node, exp.Column) else None


def _column_kind(node: exp.Column, lin: Lineage, catalog: Catalog) -> str | None:
    for ref in flows(lin, node):
        column_type = catalog.columns.get(ref.table, {}).get(ref.column)
        if column_type is not None:
            return literal_kind(column_type)
    return None
