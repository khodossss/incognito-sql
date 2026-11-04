"""Expand `*` / `t.*` into the visible columns of their base tables."""

from collections.abc import Mapping
from dataclasses import dataclass

from sqlglot import exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.optimizer.scope import Scope

from incognito_sql.core.config import ColumnClass, Declaration, column_class
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.shape import is_star

VISIBLE = frozenset({ColumnClass.OPEN, ColumnClass.QUASI, ColumnClass.IDENTIFIER})


@dataclass(frozen=True)
class StarColumn:
    """One column a star stands for: the range variable, the column name, its class."""

    source: exp.Identifier
    column: str
    cls: ColumnClass


@dataclass(frozen=True)
class Expansion:
    """The visible columns of one star, in catalog order, and how many were left out."""

    visible: tuple[StarColumn, ...]
    hidden: int


def plan_stars(
    tree: exp.Expr, lin: Lineage, catalog: Catalog, decl: Declaration
) -> dict[int, Expansion]:
    """Map id() of every star projection of `tree` to its expansion."""
    plans: dict[int, Expansion] = {}
    for select in tree.find_all(exp.Select):
        for proj in select.expressions:
            if is_star(proj):
                plans[id(proj)] = _expansion(proj, lin.scope_of(select), catalog, decl)
    return plans


def expand_stars(tree: exp.Expr, plans: Mapping[int, Expansion], dialect: str) -> None:
    """Replace, in place, every planned star by its visible columns.

    A nested SELECT left with no column selects NULL (its rows still count);
    the outer SELECT is never left empty (the caller checks that first).
    """
    for select in list(tree.find_all(exp.Select)):
        if not any(id(p) in plans for p in select.expressions):
            continue
        projections: list[exp.Expr] = []
        for proj in select.expressions:
            if id(proj) not in plans:
                projections.append(proj)
                continue
            projections.extend(
                exp.Column(this=_name(c.column, dialect), table=c.source.copy())
                for c in plans[id(proj)].visible
            )
        select.set("expressions", projections or [exp.Null()])


def _name(column: str, dialect: str) -> exp.Identifier:
    # Quoted where the dialect would fold the catalog name's case.
    ident = exp.to_identifier(column)
    return Dialect.get_or_raise(dialect).quote_identifier(ident, identify=False)


def _expansion(star: exp.Expr, scope: Scope, catalog: Catalog, decl: Declaration) -> Expansion:
    keys = [star.table] if isinstance(star, exp.Column) else list(scope.selected_sources)
    visible: list[StarColumn] = []
    hidden = 0
    for key in keys:
        table = scope.selected_sources[key][1]
        # The policy's _check_stars refused a missing or derived source; this narrows the type.
        if not isinstance(table, exp.Table):
            raise Rejection(Reason.NODE_NOT_ALLOWED)
        alias = table.args.get("alias")
        source = alias.this if isinstance(alias, exp.TableAlias) else table.this
        for column in catalog.columns.get(table.name, {}):
            cls = column_class(decl, table.name, column)
            if cls in VISIBLE:
                visible.append(StarColumn(source, column, cls))
            else:
                hidden += 1
    return Expansion(tuple(visible), hidden)
