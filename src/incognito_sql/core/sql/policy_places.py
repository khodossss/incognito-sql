"""Where an identifier value stands, and which operation of its profile that place is."""

from typing import Final, Literal

from sqlglot import exp

from incognito_sql.core.config import ColumnClass, Operation
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.flows import identifiers_in
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.policy_probes import PROBES
from incognito_sql.core.sql.policy_rules import CARRIERS, Admits, is_condition

# A subquery under these is a row source, not a value.
_SOURCE_PARENTS = (exp.From, exp.Join, exp.SetOperation)
# An operand of `=` / `IN`: which operation it is, check_comparison decides.
_COMPARED: Final = "compared"
# Holders of an ORDER BY whose keys only sort; an ordered aggregate (WITHIN GROUP) may
# return the key itself.
_SORTERS = (exp.Select, exp.SetOperation, exp.Window)


def check_places(tree: exp.Expr, lin: Lineage, admits: Admits) -> None:
    """Refuse an identifier value standing where its profile admits no operation."""
    # MIN / MAX return a value they read: their own place counts like the column's.
    for node in tree.find_all(exp.Column, exp.Subquery, *CARRIERS):
        if isinstance(node.parent, _SOURCE_PARENTS):
            continue
        if lin.ref_of(node).cls is not ColumnClass.IDENTIFIER:
            continue
        op = _place(node)
        if op == _COMPARED:
            continue
        if op is None or not all(admits(each, op) for each in identifiers_in(lin, node)):
            raise Rejection(Reason.PII_OPERATION)


# A node that takes the bare value as its argument wherever it stands; COUNT(x) tells how
# many are not NULL, as IS NOT NULL does.
_ENCLOSING: dict[type[exp.Expr], Operation] = {
    exp.Count: Operation.IS_NULL,
    exp.Length: Operation.LENGTH,
    exp.Group: Operation.GROUP,
    exp.Min: Operation.ORDER,
    exp.Max: Operation.ORDER,
}


def _place(node: exp.Expr) -> Operation | Literal["compared"] | None:
    # Which operation an identifier value takes part in where it stands: a projection,
    # GROUP BY, COUNT(DISTINCT x), COUNT(x), IS [NOT] NULL in a condition, or an operand of
    # `=` / `IN` (those are checked by check_comparison); None anywhere else.
    child, parent = node, node.parent
    while isinstance(parent, (exp.Paren, exp.Alias)):
        child, parent = parent, parent.parent
    if isinstance(parent, exp.Select):
        return Operation.OUTPUT if child.arg_key == "expressions" else None
    if isinstance(parent, exp.Distinct):
        return Operation.COUNT_DISTINCT if isinstance(parent.parent, exp.Count) else None
    if isinstance(parent, exp.Ordered):
        order = parent.parent
        holder = order.parent if order is not None else None
        return Operation.ORDER if isinstance(holder, _SORTERS) else None
    enclosing = _ENCLOSING.get(type(parent)) if parent is not None else None
    if enclosing is not None:
        return enclosing
    if isinstance(parent, exp.Is):
        return Operation.IS_NULL if _is_null_test(parent, child) else None
    return _COMPARED if isinstance(parent, (exp.EQ, exp.In, *PROBES)) else None


def _is_null_test(test: exp.Is, operand: exp.Expr) -> bool:
    # `x IS NULL` / `x IS NOT NULL` standing as a condition, x the tested side.
    if operand.arg_key != "this" or not isinstance(test.expression, exp.Null):
        return False
    stand = test.parent if isinstance(test.parent, exp.Not) else test
    return is_condition(stand)
