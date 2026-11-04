"""Which base columns a query reads: straight through to the output, or anywhere."""

from sqlglot import exp
from sqlglot.optimizer.scope import Scope

from incognito_sql.core.errors import Rejection
from incognito_sql.core.sql.expand import Expansion, StarColumn
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.shape import branches, is_star


def _base(scope: Scope | None, source: str, column: str) -> str:
    found = scope.selected_sources.get(source) if scope is not None else None
    if found is None or not isinstance(found[1], exp.Table):
        return ""
    return f"{found[1].name}.{column}".lower()


def column_origin(proj: exp.Expr, lin: Lineage) -> str:
    """Return ``table.column`` if the projection is a base-table column itself, else ``""``.

    An expression, or a column of a subquery or CTE, is not straight: its values
    may mix several columns.
    """
    col = proj.unalias()
    if not isinstance(col, exp.Column) or not col.table:
        return ""
    return _base(lin.owning_scope(col), col.table, col.name)


def star_origin(star: StarColumn, scope: Scope) -> str:
    """Return ``table.column`` for a star column read from a base table, else ``""``."""
    return _base(scope, star.source.name, star.column)


def origins(tree: exp.Expr, lin: Lineage, stars: dict[int, Expansion]) -> list[str]:
    """Return, per output column of ``tree``, its straight base column or ``""``.

    Only a single SELECT has straight columns: a set operation mixes branches.
    """
    selects = branches(tree)
    single = len(selects) == 1
    scope = lin.scope_of(selects[0])
    found: list[str] = []
    for proj in selects[0].expressions:
        if is_star(proj):
            found += [star_origin(c, scope) if single else "" for c in stars[id(proj)].visible]
        else:
            found.append(column_origin(proj, lin) if single else "")
    return found


def read_columns(tree: exp.Expr, lin: Lineage) -> list[str]:
    """Return every base column ``tree`` names, as ``table.column``, sorted.

    What the query asks about, not what the database reads: a CTE it never uses is
    named too. A column of a subquery is found where the subquery reads it; one that
    cannot be traced is left out (the policy refuses the query anyway). Star columns
    are not named here: their expansion is known once the query is prepared.
    """
    found: set[str] = set()
    for col in tree.find_all(exp.Column):
        try:
            ref = lin.source_of(col)
        except Rejection:
            continue
        if ref.table:
            found.add(f"{ref.table}.{ref.column}".lower())
    return sorted(found)
