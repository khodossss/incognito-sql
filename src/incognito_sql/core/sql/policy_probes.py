"""Probes of an identifier value: comparisons that learn a fact about it, not the value."""

from sqlglot import exp

from incognito_sql.core.config import Operation
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.families import one_family, value_families
from incognito_sql.core.sql.flows import identifiers_in
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.policy_rules import Admits, Kind, fits, is_condition, operand

ORDERING = (exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Between, exp.NEQ)
MATCHING = (exp.Like, exp.ILike)
PROBES = (*ORDERING, *MATCHING)
_WILDCARDS = ("%", "_")


def check_probe(
    pred: exp.Expr,
    lin: Lineage,
    catalog: Catalog,
    admits: Admits,
    *,
    allow_placeholders: bool,
) -> list[exp.Literal]:
    """Check one probe of an identifier; return the literals it spends from the budget.

    An ordering (`<`, `>`, `<=`, `>=`, `BETWEEN`) compares an identifier with a human
    literal of the column's type, or with another identifier of its type family; it
    stands as a condition, and the profile of every identifier behind it admits
    `order`. An open column or a token on the other side is refused: an open column
    would let the model search the value without spending literals. `<>` is checked the
    same way under `ne`, its literal compared as written (no stored spellings). A match (`LIKE`,
    `ILIKE`, either negated) takes an identifier and a human string pattern: `prefix`
    when only a trailing `%` is a wildcard, `contains` otherwise. Raises Rejection.
    """
    if isinstance(pred, MATCHING):
        return _check_match(pred, lin, admits, allow_placeholders=allow_placeholders)
    sides = (
        [pred.this, pred.args.get("low"), pred.args.get("high")]
        if isinstance(pred, exp.Between)
        else [pred.this, pred.args.get("expression")]
    )
    operands = [operand(side, lin) for side in sides if side is not None]
    idents = [n for kind, n, _ in operands if kind is Kind.IDENT]
    if not idents:
        return []
    kinds = {kind for kind, _, _ in operands}
    allowed = {Kind.IDENT, Kind.LITERAL} | ({Kind.PLACEHOLDER} if allow_placeholders else set())
    if not kinds <= allowed or not is_condition(pred):
        raise Rejection(Reason.PII_OPERATION)
    behind = [ref for node in idents for ref in identifiers_in(lin, node)]
    op = Operation.NE if isinstance(pred, exp.NEQ) else Operation.ORDER
    if not all(admits(ref, op) for ref in behind):
        raise Rejection(Reason.PII_OPERATION)
    if not one_family([value_families(n, lin, catalog) for n in idents]):
        raise Rejection(Reason.LITERAL_TYPE_MISMATCH)
    literals = [n for kind, n, _ in operands if kind is Kind.LITERAL]
    if not all(fits(lit, ref, catalog) for lit in literals for ref in behind):
        raise Rejection(Reason.LITERAL_TYPE_MISMATCH)
    return [lit for lit in literals if isinstance(lit, exp.Literal)]


def _check_match(
    pred: exp.Like | exp.ILike, lin: Lineage, admits: Admits, *, allow_placeholders: bool
) -> list[exp.Literal]:
    subject, pattern = operand(pred.this, lin), operand(pred.expression, lin)
    if subject[0] is not Kind.IDENT and pattern[0] is not Kind.IDENT:
        return []
    bound = allow_placeholders and pattern[0] is Kind.PLACEHOLDER
    literal = pattern[0] is Kind.LITERAL and isinstance(pattern[1], exp.Literal)
    if subject[0] is not Kind.IDENT or not (bound or literal) or not is_condition(pred):
        raise Rejection(Reason.PII_OPERATION)
    behind = identifiers_in(lin, subject[1])
    if bound:  # the first check admitted the pattern it stands for
        ops = (Operation.PREFIX, Operation.CONTAINS)
        if not all(any(admits(ref, op) for op in ops) for ref in behind):
            raise Rejection(Reason.PII_OPERATION)
        return []
    text = pattern[1]
    if not isinstance(text, exp.Literal) or not text.is_string:
        raise Rejection(Reason.LITERAL_TYPE_MISMATCH)
    op = Operation.PREFIX if _is_prefix(text.name) else Operation.CONTAINS
    if not all(admits(ref, op) for ref in behind):
        raise Rejection(Reason.PII_OPERATION)
    return [text]


def _is_prefix(pattern: str) -> bool:
    # `abc%` or `abc`: no wildcard but one trailing `%`.
    body = pattern.removesuffix("%")
    return bool(body) and not any(w in body for w in _WILDCARDS)
