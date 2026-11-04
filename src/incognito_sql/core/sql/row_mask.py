"""Row rules at execution: a table with a rule is read through a masked copy of itself.

The policy has judged the query on the columns as declared; the server then puts in a
fixed form of its own, so
every comparison, join and aggregate meets the hidden cells already NULL.
"""

from collections import defaultdict

from sqlglot import exp

from incognito_sql.core.config import Declaration, column_class
from incognito_sql.core.config.row_rules import RowRule, condition
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.expand import VISIBLE
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.scan_fallible import fallible


def mask_rows(tree: exp.Expr, decl: Declaration, catalog: Catalog) -> exp.Expr:
    """Replace each reference to a table with row rules by its masked copy; return the tree."""
    rules: dict[str, list[RowRule]] = defaultdict(list)
    for rule in decl.row_rules:
        rules[rule.table.lower()].append(rule)
    if not rules:
        return tree
    named = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    if named & rules.keys():  # a WITH query named like the table would hide which is read
        raise Rejection(Reason.NODE_NOT_ALLOWED)
    for table in list(tree.find_all(exp.Table)):
        found = rules.get(table.name.lower())
        source = catalog.table(table.name)
        if found is None or source is None:
            continue
        alias = table.args.get("alias")
        name = alias.this.copy() if isinstance(alias, exp.TableAlias) else table.this.copy()
        masked = _masked(table, source, found, catalog, decl.dialect)
        table.replace(exp.Subquery(this=masked, alias=exp.TableAlias(this=name)))
    return tree


def _masked(
    table: exp.Table, source: str, rules: list[RowRule], catalog: Catalog, dialect: str
) -> exp.Select:
    # Shown only where every rule's condition is false: true or unknown hides.
    shown: dict[str, list[exp.Expr]] = defaultdict(list)
    kept: list[exp.Expr] = []
    for rule in rules:
        clear = exp.Not(this=exp.Paren(this=condition(rule, dialect)))
        if rule.hide == "*":
            kept.append(clear)
        for column in rule.hide if rule.hide != "*" else []:
            shown[column.lower()].append(clear)
    plain = exp.Table(this=table.this.copy(), db=table.args.get("db"))
    select = exp.select(*_columns(source, shown, catalog)).from_(plain)
    return select.where(exp.and_(*kept)) if kept else select


def _columns(source: str, shown: dict[str, list[exp.Expr]], catalog: Catalog) -> list[exp.Expr]:
    out: list[exp.Expr] = []
    for column in catalog.columns[source]:
        ref = exp.column(column, quoted=True)
        conditions = shown.get(column.lower())
        if conditions:
            case = exp.Case(ifs=[exp.If(this=exp.and_(*conditions), true=ref)])
            out.append(exp.alias_(case, exp.to_identifier(column, quoted=True)))
        else:
            out.append(ref)
    return out


_Key = tuple[str | tuple[str, ...], str]


def unruled_readers(decl: Declaration, catalog: Catalog) -> list[str]:
    """Name each open relation that may show a ruled table's rows past its rule.

    A view, with a rule of its own or not, while any table has one: it reads its
    tables as they are, and which tables it reads is not worked out. A table of a family joined by
    inheritance (partitions, child and parent tables, either way and at any depth)
    that lacks a rule some table of its family has: its rows are read through the
    others, and a query is masked only by the rules of the table it names (node
    #110). Which rule is stricter is not worked out. One listed in
    `verified_relations` is not named, nor one without open columns.
    """
    own: dict[str, frozenset[_Key]] = defaultdict(frozenset)
    for rule in decl.row_rules:
        own[rule.table.lower()] |= {_key(rule)}
    if not own:
        return []
    families = _families(catalog)

    def short(name: str) -> bool:
        if name in catalog.views:  # its own rule masks it, but which rows it shows is unknown
            return True
        family = families.get(name, frozenset({name}))
        needed = frozenset[_Key]().union(*(own[member.lower()] for member in family))
        return not needed <= own[name.lower()]

    return [
        name
        for name in sorted(catalog.columns)
        if short(name)
        and name.lower() not in decl.verified_relations
        and any(column_class(decl, name, c) in VISIBLE for c in catalog.columns[name])
    ]


def _key(rule: RowRule) -> _Key:
    # Two tables carry the same rule when it hides the same columns under the same text.
    hide = "*" if rule.hide == "*" else tuple(sorted(c.lower() for c in rule.hide))
    return hide, rule.where.strip()


def _families(catalog: Catalog) -> dict[str, frozenset[str]]:
    # Tables joined by inheritance, either way and at any depth.
    links: dict[str, set[str]] = defaultdict(set)
    for child, parents in catalog.parents.items():
        for parent in parents:
            links[child].add(parent)
            links[parent].add(child)
    out: dict[str, frozenset[str]] = {}
    for start in links:
        if start in out:
            continue
        seen, todo = {start}, [start]
        while todo:
            for other in links[todo.pop()] - seen:
                seen.add(other)
                todo.append(other)
        for member in seen:
            out[member] = frozenset(seen)
    return out


def check_dropped_rows(tree: exp.Expr, lin: Lineage, catalog: Catalog) -> None:
    """Refuse an expression that can fail in a query that reads a table whose rows a rule drops.

    A planner may evaluate it before the masked copy's filter, wherever it stands and
    whichever table it reads (a join pairs rows before the filter too): failing, or not,
    on a dropped row would tell the row is there. SUM / AVG themselves read
    only the rows kept.
    """
    dropping = {r.table.lower() for r in lin.decl.row_rules if r.hide == "*"}
    if not any(table.name.lower() in dropping for table in tree.find_all(exp.Table)):
        return
    found = fallible(tree, lin, catalog, every_constant=True)
    if any(not isinstance(node, exp.Sum | exp.Avg) for node in found):
        raise Rejection(Reason.HIDDEN_ROWS)
