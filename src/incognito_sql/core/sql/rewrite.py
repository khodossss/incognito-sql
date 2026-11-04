"""Regenerate a checked query as SQL whose values are all bind parameters."""

from dataclasses import dataclass
from datetime import datetime
from functools import cache
from typing import cast

from sqlglot import exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.generator import Generator

from incognito_sql.core.config import ColumnClass, Declaration
from incognito_sql.core.sql.bind import bind_literals, plan_pii
from incognito_sql.core.sql.binder import Binder
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.expand import Expansion, expand_stars, plan_stars
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.origin import origins
from incognito_sql.core.sql.policy import PolicyResult
from incognito_sql.core.sql.recheck import PLAIN_NAME, recheck
from incognito_sql.core.sql.row_mask import mask_rows
from incognito_sql.core.sql.shadow import WRITTEN
from incognito_sql.core.sql.shape import branches, is_star
from incognito_sql.core.sql.tiebreak import add_tiebreaks, plan_tiebreaks
from incognito_sql.core.tokens.store import TokenStore


@dataclass(frozen=True)
class Prepared:
    """SQL ready to execute with `params`, and what its output columns are.

    `hidden_count`: columns of the outer `*` / `t.*` left out as hidden.
    `output_classes`: the class of each output column (identifier ones are to be
    tokenized). `ordered`: the outer query has ORDER BY keys, so the rows come back
    in that order. `origins`: per output column, the base `table.column` it passes
    straight through, else "". An empty `sql` means no visible column was left to select.
    """

    sql: str
    params: dict[str, object]
    hidden_count: int
    output_classes: list[ColumnClass | None]
    ordered: bool = False
    origins: tuple[str, ...] = ()


def prepare(  # noqa: PLR0913, PLR0917 -- the pipeline's fixed interface
    tree: exp.Expr,
    policy: PolicyResult,
    store: TokenStore,
    catalog: Catalog,
    decl: Declaration,
    now: datetime,
) -> Prepared:
    """Rewrite the tree `enforce` approved into executable SQL, then check that SQL again.

    Stars become the visible columns of their tables; a literal or token compared
    to an identifier becomes `IN` over every raw form of its value; every other
    value literal becomes a bind parameter (equal values share one); every query
    with LIMIT / OFFSET, and the outer one, gets a random last sort key. Raises
    Rejection (e.g. INVALID_TOKEN, LIMIT_EXCEEDED, NODE_NOT_ALLOWED for a name that
    is not a plain identifier).
    The input tree is not changed.
    """
    lin = Lineage(tree, catalog, decl)
    stars = plan_stars(tree, lin, catalog, decl)
    classes, hidden = _outputs(tree, lin, stars, policy)
    if not classes:
        return Prepared("", {}, hidden, [])
    pii = plan_pii(policy, lin, catalog)
    ties = plan_tiebreaks(tree)
    work = tree.copy()
    twin = {id(a): id(b) for a, b in zip(tree.walk(), work.walk(), strict=True)}
    _rename_value_aliases(work)  # before binding: it reads the literal
    binder = Binder(store, now, decl.dialect)
    bind_literals(work, {twin[k]: v for k, v in pii.items()}, binder)
    expand_stars(work, {twin[k]: v for k, v in stars.items()}, decl.dialect)
    _drop_self_aliases(work)
    taken = {a.name.lower() for a in work.find_all(exp.TableAlias)} | set(catalog.columns)
    work = add_tiebreaks(work, {twin[k] for k in ties}, taken, decl.dialect)
    sql = render(work, decl.dialect)
    recheck(sql, binder.params, catalog, decl)
    if decl.row_rules:  # after the recheck: the masked copies are the server's own SQL
        sql = render(mask_rows(work, decl, catalog), decl.dialect)
    # An identifier sort key is the `order` operation of the profile; the model's order
    # is shown as asked;
    # ties keep the random last key.
    order = tree.args.get("order")
    ordered = isinstance(order, exp.Order) and bool(order.expressions)
    return Prepared(sql, binder.params, hidden, classes, ordered, tuple(origins(tree, lin, stars)))


def _outputs(
    tree: exp.Expr, lin: Lineage, stars: dict[int, Expansion], policy: PolicyResult
) -> tuple[list[ColumnClass | None], int]:
    classes: list[ColumnClass | None] = []
    hidden = 0
    for i, proj in enumerate(branches(tree)[0].expressions):
        if is_star(proj):
            classes += [c.cls for c in stars[id(proj)].visible]
            hidden += stars[id(proj)].hidden
            continue
        cls = lin.output(tree, index=i).cls
        classes.append(ColumnClass.IDENTIFIER if i in policy.pii_outputs else cls)
    return classes, hidden


def _drop_self_aliases(tree: exp.Expr) -> None:
    # qualify writes `people AS people` and `c AS c` (for a CTE); the re-check
    # would read those as repeated aliases or a CTE named like an alias.
    for table in tree.find_all(exp.Table):
        alias = table.args.get("alias")
        if isinstance(alias, exp.TableAlias) and alias.this == table.this:
            table.set("alias", None)


def _rename_value_aliases(tree: exp.Expr) -> None:
    # qualify names an unaliased value after its text (`SELECT 1` -> `AS "1"`,
    # `CAST(COUNT(*) AS TEXT)` -> `AS "*"`) or after the column inside it
    # (`CAST(city AS TEXT)` -> `AS city`, which would shadow that column in the
    # re-check); such a name gets qualify's own `_col_<position>`. A bare column keeps
    # its own name. Any reference to an old name that is not plain is refused by the
    # re-check.
    for select in tree.find_all(exp.Select):
        for i, proj in enumerate(select.expressions):
            if (
                not isinstance(proj, exp.Alias)
                or proj.alias.lower() != proj.this.output_name.lower()
            ):
                continue
            generated = not proj.meta.get(WRITTEN) and not isinstance(proj.this, exp.Column)
            if generated or not PLAIN_NAME.fullmatch(proj.alias):
                proj.set("alias", exp.to_identifier(f"_col_{i}"))


def _named_placeholder(_gen: Generator, expression: exp.Placeholder) -> str:
    return f":{expression.name}"


@cache
def _generator_class(dialect: str) -> type[Generator]:
    # The dialect's own SQL, except that placeholders are `:name` as SQLAlchemy
    # `text()` expects (PostgreSQL would render `%(name)s`).
    base = Dialect.get_or_raise(dialect).generator_class
    named = type("NamedGenerator", (base,), {"placeholder_sql": _named_placeholder})
    return cast("type[Generator]", named)


def render(tree: exp.Expr, dialect: str) -> str:
    """Generate the dialect's SQL for a tree, with placeholders written as `:name`."""
    reader = Dialect.get_or_raise(dialect)
    return _generator_class(dialect)(dialect=reader, comments=False).generate(tree)
