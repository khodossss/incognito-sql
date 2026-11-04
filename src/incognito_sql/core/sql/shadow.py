"""Refuse names that shadow other names: the cases where readers of SQL disagree."""

from collections import Counter

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.shape import branches, is_star, star_sources, visible_scopes


def check_names(tree: exp.Expr, catalog: Catalog) -> None:
    """Refuse duplicate CTE names or table aliases, and CTEs named like a table or alias.

    A table alias may repeat only across branches of a set operation.

    Runs on the tree as written (before qualification adds aliases). Names are
    compared case-insensitively. Raises Rejection(AMBIGUOUS_COLUMN).
    """
    ctes = [cte.alias.lower() for cte in tree.find_all(exp.CTE)]
    held = [a for a in tree.find_all(exp.TableAlias) if not isinstance(a.parent, exp.CTE)]
    aliases = [alias.name.lower() for alias in held]
    tables = {name.lower() for name in catalog.columns}
    if any(n > 1 for n in Counter(ctes).values()) or _repeated(held):
        raise Rejection(Reason.AMBIGUOUS_COLUMN)
    if any(cte in tables or cte in aliases for cte in ctes):
        raise Rejection(Reason.AMBIGUOUS_COLUMN)


def _repeated(held: list[exp.TableAlias]) -> bool:
    # One alias twice is ambiguous unless the two sit in different branches of a set
    # operation: each branch is its own scope, as in `... T1 ... INTERSECT ... T1 ...`.
    for i, first in enumerate(held):
        for second in held[i + 1 :]:
            same = first.name.lower() == second.name.lower()
            if same and not _apart(first, second):
                return True
    return False


def _apart(first: exp.Expr, second: exp.Expr) -> bool:
    sides = dict(_branches_of(first))
    return any(sides.get(op, side) != side for op, side in _branches_of(second))


def _branches_of(node: exp.Expr) -> list[tuple[int, str]]:
    # Each set operation above `node`, with the side (`this` or `expression`) it is on.
    found = []
    child, parent = node, node.parent
    while parent is not None:
        if isinstance(parent, exp.SetOperation) and child.arg_key in ("this", "expression"):
            found.append((id(parent), child.arg_key))
        child, parent = parent, parent.parent
    return found


WRITTEN = "written_alias"


def mark_written_aliases(tree: exp.Expr) -> None:
    """Mark the aliases the query itself writes; qualify adds others for unaliased values."""
    for alias in tree.find_all(exp.Alias):
        alias.meta[WRITTEN] = True


def check_aliases(tree: exp.Expr, catalog: Catalog) -> None:
    """Refuse a projection alias equal to a column name its SELECT can see.

    Visible: the SELECT's FROM sources and those of every enclosing query reached
    across at least one subquery boundary (see `visible_scopes`).

    Runs on the qualified tree. A bare column aliased to its own name is fine, and so
    is a name qualify gave an unaliased value (`CAST(city AS TEXT)` -> `AS city`): the
    query never wrote it, so nothing in it can mean that name.
    Raises Rejection(AMBIGUOUS_COLUMN).
    """
    for scope in traverse_scope(tree):
        if not isinstance(scope.expression, exp.Select):
            continue
        names = {
            name
            for seen in visible_scopes(scope)
            for _, source in seen.selected_sources.values()
            for name in _column_names(source, catalog)
        }
        for proj in scope.expression.expressions:
            if not isinstance(proj, exp.Alias) or not proj.meta.get(WRITTEN):
                continue
            alias = proj.alias.lower()
            same = isinstance(proj.this, exp.Column) and proj.this.name.lower() == alias
            if alias in names and not same:
                raise Rejection(Reason.AMBIGUOUS_COLUMN)


def _column_names(source: exp.Table | Scope, catalog: Catalog) -> set[str]:
    if isinstance(source, exp.Table):
        return {c.lower() for c in catalog.columns.get(source.name, {})}
    first = branches(source.expression)[0]
    names = {p.alias_or_name.lower() for p in first.expressions if not is_star(p)}
    for star in (p for p in first.expressions if is_star(p)):
        for inner in star_sources(star, source):
            names |= _column_names(inner, catalog)
    return names
