"""Spellings a collation holds equal: the scan picks the one an answer shows."""

from sqlglot import exp

from incognito_sql.core.config import ColumnClass
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.flows import flows
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.shape import branches
from incognito_sql.core.sql.typefamily import TEXT, literal_kind


def check_spellings(tree: exp.Expr, lin: Lineage, catalog: Catalog) -> None:
    """Refuse showing one of equal open text spellings: the scan picks it.

    Among values the collation holds equal (in case; in accents on MySQL, trailing spaces
    on SQL Server, which lower() and upper() do not part) the answer shows the spelling met
    first, and a key, an index or a joined table can lead the scan in an identifier's order
    in more ways than the server can see.
    """
    chosen: list[exp.Expr] = []
    for select in tree.find_all(exp.Select):
        chosen += [*_group_keys(select), *_aggregated(select)]
        if select.args.get("distinct") is not None:
            chosen += select.expressions
    for setop in tree.find_all(exp.SetOperation):
        if setop.args.get("distinct"):
            chosen += [p for s in branches(setop) for p in s.expressions]
    if any(_open_text(node, lin, catalog) for node in chosen):
        raise Rejection(Reason.EQUAL_SPELLINGS)


def own(select: exp.Select, node: exp.Expr) -> bool:
    """Tell whether ``node`` belongs to ``select`` itself, not to a query nested in it."""
    return node.find_ancestor(exp.Select) is select


def _group_keys(select: exp.Select) -> list[exp.Expr]:
    group = select.args.get("group")
    return list(group.expressions) if group is not None else []


def _aggregated(select: exp.Select) -> list[exp.Expr]:
    return [agg.this for agg in select.find_all(exp.Min, exp.Max) if own(select, agg)]


def _open_text(node: exp.Expr, lin: Lineage, catalog: Catalog) -> bool:
    return any(
        ref.cls is not ColumnClass.IDENTIFIER
        and literal_kind(catalog.columns.get(ref.table, {}).get(ref.column, "")) == TEXT
        for col in node.find_all(exp.Column)
        for ref in flows(lin, col)
    )
