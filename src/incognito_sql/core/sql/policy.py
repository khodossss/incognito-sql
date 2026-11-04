"""Default-deny policy for personal columns over a qualified query."""

from dataclasses import dataclass, field

from sqlglot import exp

from incognito_sql.core.config import ColumnClass, Declaration, Operation, column_operations
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.colref import ColumnRef
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.policy_places import check_places
from incognito_sql.core.sql.policy_probes import PROBES, check_probe
from incognito_sql.core.sql.policy_rules import check_comparison, is_token
from incognito_sql.core.sql.policy_shape import check_mentions
from incognito_sql.core.sql.probe_count import count_probes
from incognito_sql.core.sql.shape import branches, is_star


@dataclass
class PolicyResult:
    """What the rewrite must handle in a query that passed the policy.

    `pii_outputs`: indexes of the outer projections that carry identifier values
    (star projections are not classified here). `pii_literals` / `pii_tokens`:
    the literal nodes compared to identifier values, split by token shape.
    `probe_literals`: literals of probes (`<`, `LIKE` ...) of identifier values; they
    spend the literal budget and bind as plain values. `probes`: how many L3 probes of
    identifier values the query holds; they spend the probe budget.
    """

    pii_outputs: list[int] = field(default_factory=list)
    pii_literals: list[exp.Literal] = field(default_factory=list)
    pii_tokens: list[exp.Literal] = field(default_factory=list)
    probe_literals: list[exp.Literal] = field(default_factory=list)
    probes: int = 0


def enforce(
    tree: exp.Expr,
    catalog: Catalog,
    decl: Declaration,
    *,
    allow_placeholders: bool = False,
) -> PolicyResult:
    """Check a tree from `qualify_tree`; raise Rejection on the first violation.

    An identifier value may only be output as is, grouped, counted with
    COUNT(DISTINCT ...) or COUNT(x), tested by IS [NOT] NULL in a condition, measured
    by length(), sorted, taken by MIN / MAX, compared by `<` `>` `BETWEEN` (a probe),
    or compared by `=` / `IN` with a token, a literal of the column's type, another
    identifier, or (when `allow_placeholders`, for SQL the server rewrote) a bind
    placeholder; that flag also admits the random sort key the rewrite appends. Each
    of these must also be an operation the protection profile of the column admits.
    Any mention of a hidden column is refused.
    A `*` / `t.*` may only expand base tables.

    The SQL to execute must be regenerated from this same qualified tree (the
    literal nodes in the result belong to it). `pii_outputs` indexes the
    projection list before star expansion.
    """
    lin = Lineage(tree, catalog, decl)
    check_mentions(tree, lin, catalog, allow_rewrite=allow_placeholders)

    def admits(ref: ColumnRef, op: Operation) -> bool:
        return op in column_operations(decl, ref.table, ref.column)

    check_places(tree, lin, admits)
    result = PolicyResult()
    for pred in tree.find_all(exp.EQ, exp.In):
        if not isinstance(pred, (exp.EQ, exp.In)):  # narrows the type only
            continue
        literals = check_comparison(
            pred, lin, catalog, admits, allow_placeholders=allow_placeholders
        )
        for lit in literals:
            (result.pii_tokens if is_token(lit) else result.pii_literals).append(lit)
    for probe in tree.find_all(*PROBES):
        result.probe_literals += check_probe(
            probe, lin, catalog, admits, allow_placeholders=allow_placeholders
        )
    first = branches(tree)[0].expressions
    result.probes = count_probes(tree, lin)
    result.pii_outputs = [
        i
        for i, proj in enumerate(first)
        if not is_star(proj) and lin.output(tree, index=i).cls is ColumnClass.IDENTIFIER
    ]
    return result
