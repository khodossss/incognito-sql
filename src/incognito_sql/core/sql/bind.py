"""Turn every value literal of a checked query into a bind parameter."""

from collections.abc import Mapping

from sqlglot import exp

from incognito_sql.core.config import ColumnClass
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.bind_values import literal_value
from incognito_sql.core.sql.binder import MAX_FORMS, Binder, PiiLiteral
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.order_keys import strip_parens
from incognito_sql.core.sql.policy import PolicyResult
from incognito_sql.core.sql.policy_rules import CARRIERS


def plan_pii(policy: PolicyResult, lin: Lineage, catalog: Catalog) -> dict[int, PiiLiteral]:
    """Map id() of each literal compared to an identifier to how it must be expanded."""
    plan: dict[int, PiiLiteral] = {}
    for literals, token in ((policy.pii_literals, False), (policy.pii_tokens, True)):
        for lit in literals:
            ref = lin.ref_of(_identifier(lit, lin))
            plan[id(lit)] = PiiLiteral(token, catalog.columns[ref.table][ref.column])
    return plan


def bind_literals(tree: exp.Expr, pii: Mapping[int, PiiLiteral], binder: Binder) -> None:
    """Rewrite `tree` in place: compared literals to `IN (variants)`, the rest to binds.

    Integer positions in ORDER BY / GROUP BY, LIMIT / OFFSET values and type
    arguments stay literal: they are syntax, not values. Limits count what the
    model wrote, never the stored forms: a query whose items could need more bind
    parameters than the dialect takes is refused (LIMIT_EXCEEDED) whatever is
    stored; `parse` refused an `IN` past `max_in_items` items.
    """
    values_written = [lit for lit in tree.find_all(exp.Literal) if not is_syntax(lit)]
    if len(values_written) + len(pii) * (MAX_FORMS - 1) + 2 > binder.max_params:
        raise Rejection(Reason.LIMIT_EXCEEDED)  # +2: the binds of a constant false
    _flip_literal_in(tree, pii)
    for pred in list(tree.find_all(exp.EQ, exp.In)):
        items = [pred.this, pred.expression] if isinstance(pred, exp.EQ) else pred.expressions
        lits = [s for s in map(strip_parens, items) if isinstance(s, exp.Literal) and id(s) in pii]
        if not lits:
            continue
        keep = [i for i in items if id(strip_parens(i)) not in pii]
        values = list(
            dict.fromkeys(
                (v, pii[id(lit)].column_type)
                for lit in lits
                for v in binder.variants(lit, pii[id(lit)])
            )
        )
        binds = [binder.bind_as(v, column_type) for v, column_type in values]
        if not binds and (isinstance(pred, exp.EQ) or not keep):
            # No form the column's type holds: false, as when no row has the value.
            pred.replace(exp.EQ(this=binder.bind(1), expression=binder.bind(0)))
        elif isinstance(pred, exp.EQ):
            pred.replace(exp.In(this=keep[0], expressions=binds))
        else:
            pred.set("expressions", [*keep, *binds])
    for lit in list(tree.find_all(exp.Literal)):
        if not is_syntax(lit):
            lit.replace(binder.bind(literal_value(lit)))


def _flip_literal_in(tree: exp.Expr, pii: Mapping[int, PiiLiteral]) -> None:
    """Rewrite `'x' IN (name)` to `name = 'x'`; refuse a literal against a longer list.

    With the literal on the left it would be bound as written, and a token or another
    spelling of the value would match nothing. The policy refuses the longer list first
    (policy_rules._literal_left_of_list), before the literal spends the budget.
    """
    for pred in list(tree.find_all(exp.In)):
        if id(strip_parens(pred.this)) not in pii:
            continue
        if len(pred.expressions) != 1:
            raise Rejection(Reason.PII_OPERATION)
        pred.replace(exp.EQ(this=pred.expressions[0], expression=pred.this))


def is_syntax(lit: exp.Literal) -> bool:
    """Tell whether a literal is syntax (position, LIMIT, type argument) rather than a value."""
    if lit.is_string:
        return False
    node: exp.Expr = lit
    while isinstance(node.parent, exp.Paren):
        node = node.parent
    if isinstance(node.parent, exp.Ordered | exp.Group) and node.arg_key in {"this", "expressions"}:
        return True
    if isinstance(lit.parent, exp.DataTypeParam):
        return True
    up = lit.parent
    while up is not None and not isinstance(up, exp.Query):
        if isinstance(up, exp.Limit | exp.Offset):
            return True
        up = up.parent
    return False


def _identifier(lit: exp.Expr, lin: Lineage) -> exp.Expr:
    pred = lit.parent
    while isinstance(pred, exp.Paren):
        pred = pred.parent
    items = (
        [pred.this, pred.expression]
        if isinstance(pred, exp.EQ)
        else [pred.this, *pred.expressions]
        if isinstance(pred, exp.In)
        else []
    )
    for side in map(strip_parens, items):
        if (
            isinstance(side, (exp.Column, exp.Subquery, *CARRIERS))
            and lin.ref_of(side).cls is ColumnClass.IDENTIFIER
        ):
            return side
    raise Rejection(Reason.PII_OPERATION)
