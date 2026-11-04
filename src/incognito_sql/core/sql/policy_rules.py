"""Comparison rules for identifier values: `=` and `IN` with what, and where."""

from collections.abc import Callable
from enum import Enum, auto

from sqlglot import exp

from incognito_sql.core.config import ColumnClass, Operation
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.colref import ColumnRef
from incognito_sql.core.sql.families import one_family, value_families
from incognito_sql.core.sql.flows import identifiers_in, identifiers_out
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.typefamily import NUMBER, TEXT, literal_kind
from incognito_sql.core.tokens.format import TOKEN_RE

_OPEN = (ColumnClass.OPEN, ColumnClass.QUASI)


class Kind(Enum):
    """What an operand of a comparison is."""

    IDENT = auto()
    TOKEN = auto()
    LITERAL = auto()
    PLACEHOLDER = auto()
    OPEN = auto()
    OTHER = auto()


Operand = tuple[Kind, exp.Expr, ColumnRef | None]
# Aggregates whose result is one of the values they read: an identifier's value itself.
CARRIERS = (exp.Min, exp.Max)
Admits = Callable[[ColumnRef, Operation], bool]


def check_comparison(
    pred: exp.EQ | exp.In,
    lin: Lineage,
    catalog: Catalog,
    admits: Admits,
    *,
    allow_placeholders: bool,
) -> list[exp.Literal]:
    """Check one `=` / `IN`; return its literal operands if it touches an identifier.

    Raises Rejection when an identifier is compared to anything but a token, a
    literal of the column's type, a placeholder (re-check only) or another
    identifier, when the comparison is not a plain condition (e.g. under NOT), or
    when a compared identifier's profile does not admit the comparison.
    """
    sides = [pred.this, pred.expression] if isinstance(pred, exp.EQ) else [pred.this]
    operands = [operand(side, lin) for side in [*sides, *pred.expressions]]
    query = pred.args.get("query")
    if query is not None:
        ref = lin.output(query, index=0)
        operands.append(
            (Kind.IDENT if ref.cls is ColumnClass.IDENTIFIER else Kind.OPEN, query, ref)
        )
    idents = [ref for kind, _, ref in operands if kind is Kind.IDENT and ref is not None]
    if not idents:
        return []
    kinds = {kind for kind, _, _ in operands}
    if Kind.OTHER in kinds or (Kind.PLACEHOLDER in kinds and not allow_placeholders):
        raise Rejection(Reason.PII_OPERATION)
    if Kind.OPEN in kinds:
        raise Rejection(Reason.PII_JOIN_WITH_OPEN)
    if not is_condition(pred) or _literal_left_of_list(pred, operands):
        raise Rejection(Reason.PII_OPERATION)
    # Each identifier behind each compared side answers for its own profile.
    behind = [
        ref
        for kind, node, _ in operands
        if kind is Kind.IDENT
        for ref in (identifiers_out(lin, node, 0) if node is query else identifiers_in(lin, node))
    ]
    if not all(admits(ref, op) for ref in behind for op in _operations(kinds, len(idents))):
        raise Rejection(Reason.PII_OPERATION)
    compared = [value_families(n, lin, catalog) for kind, n, _ in operands if kind is Kind.IDENT]
    if not one_family(compared):
        # A cast between families can fail on some values only: a 1-bit channel.
        raise Rejection(Reason.LITERAL_TYPE_MISMATCH)
    literals = [n for kind, n, _ in operands if kind in (Kind.TOKEN, Kind.LITERAL)]
    for kind, node, _ in operands:
        if kind is Kind.LITERAL and not all(fits(node, ref, catalog) for ref in idents):
            raise Rejection(Reason.LITERAL_TYPE_MISMATCH)
    return [n for n in literals if isinstance(n, exp.Literal)]


def is_token(lit: exp.Literal) -> bool:
    """Whether a literal has the shape of a token."""
    return bool(lit.is_string and TOKEN_RE.match(lit.name))


def operand(node: exp.Expr, lin: Lineage) -> Operand:
    """Classify one operand of a comparison: an identifier, a token, a literal, ..."""
    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, exp.Literal):
        return (Kind.TOKEN if is_token(node) else Kind.LITERAL, node, None)
    if isinstance(node, exp.Placeholder) or (
        isinstance(node, exp.Cast) and isinstance(node.this, exp.Placeholder)
    ):  # the rewrite casts a bind to its identifier's exact type
        return (Kind.PLACEHOLDER, node, None)
    if isinstance(node, (exp.Column, exp.Subquery, *CARRIERS)):
        ref = lin.ref_of(node)
        if ref.cls is ColumnClass.IDENTIFIER:
            return (Kind.IDENT, node, ref)
        if isinstance(node, (exp.Column, *CARRIERS)) and ref.cls in _OPEN:
            return (Kind.OPEN, node, ref)
    return (Kind.OTHER, node, None)


def _operations(kinds: set[Kind], idents: int) -> list[Operation]:
    # What a comparison does with each identifier in it. A placeholder stands for a
    # token or literal the first check already admitted.
    ops = [Operation.EQ_TOKEN] if Kind.TOKEN in kinds else []
    if Kind.LITERAL in kinds:
        ops.append(Operation.EQ_LITERAL)
    if idents > 1:
        ops.append(Operation.JOIN_IDENT)
    return ops


def _literal_left_of_list(pred: exp.EQ | exp.In, operands: list[Operand]) -> bool:
    # `'x' IN (a, b)`: the rewrite turns a literal on the left into `=` against one item
    # only (bind._flip_literal_in); refused here, before the literal spends the budget.
    return (
        isinstance(pred, exp.In) and operands[0][0] is not Kind.IDENT and len(pred.expressions) != 1
    )


def is_condition(pred: exp.Expr) -> bool:
    """Whether only AND / OR / parentheses stand between a test and its clause."""
    child, parent = pred, pred.parent
    while isinstance(parent, (exp.Paren, exp.And, exp.Or)):
        child, parent = parent, parent.parent
    if isinstance(parent, (exp.Where, exp.Having, exp.If)):
        return child.arg_key == "this"
    return isinstance(parent, exp.Join) and child.arg_key == "on"


def fits(lit: exp.Expr, ref: ColumnRef, catalog: Catalog) -> bool:
    """Tell whether a literal has the type family of the column (text or number)."""
    is_string = isinstance(lit, exp.Literal) and lit.is_string
    col_type = catalog.columns.get(ref.table, {}).get(ref.column, "")
    return literal_kind(col_type) == (TEXT if is_string else NUMBER)
