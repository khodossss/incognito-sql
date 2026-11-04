"""How many L3 probes of identifier values a query holds."""

from sqlglot import exp

from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.policy_probes import MATCHING, PROBES
from incognito_sql.core.sql.policy_rules import Kind, operand

# Places that sort or measure the value they hold: `order` and `length`.
_PLACES = (exp.Ordered, exp.Min, exp.Max, exp.Length)


def count_probes(tree: exp.Expr, lin: Lineage) -> int:
    """Return the number of nodes that probe an identifier value.

    A comparison `<` `>` `BETWEEN` `<>` or a `LIKE` with an identifier on a side, and a
    sort key, `MIN` / `MAX` or `length()` over one. One node is one probe, whatever
    the rows it meets.
    """
    probes = sum(1 for node in tree.find_all(*PROBES) if _touches(node, lin))
    places = sum(1 for node in tree.find_all(*_PLACES) if operand(node.this, lin)[0] is Kind.IDENT)
    return probes + places


def _touches(node: exp.Expr, lin: Lineage) -> bool:
    if isinstance(node, (*MATCHING, exp.Between)):
        sides = (
            [node.this, node.expression]
            if isinstance(node, MATCHING)
            else [node.this, node.args.get("low"), node.args.get("high")]
        )
    else:
        sides = [node.this, node.args.get("expression")]
    return any(operand(side, lin)[0] is Kind.IDENT for side in sides if side is not None)
