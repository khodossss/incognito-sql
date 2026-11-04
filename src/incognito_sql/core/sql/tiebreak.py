"""Random tiebreak: rows that are cut or capped come out in random order."""

from collections.abc import Collection

from sqlglot import exp

from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.order_keys import is_position, strip_parens
from incognito_sql.core.sql.shape import branches, unwrap


# A random last sort key wherever rows are cut or capped.
def plan_tiebreaks(tree: exp.Expr) -> set[int]:
    """Return id() of every query that needs a random last sort key.

    That is every SELECT / UNION with LIMIT or OFFSET, at any depth and whatever
    it outputs (a cut picks rows by the scan order, which may follow an index on
    a personal column); every subquery used as a value (SQLite reads it as an
    implicit LIMIT 1); and the outer one (the row cap is a LIMIT in effect).
    """
    found = {
        id(query)
        for query in tree.find_all(exp.Select, exp.SetOperation)
        if query is tree or query.args.get("limit") or query.args.get("offset")
    }
    for sub in tree.find_all(exp.Subquery):
        source = isinstance(sub.parent, exp.From | exp.Join | exp.SetOperation)
        listed = isinstance(sub.parent, exp.In) and sub.arg_key == "query"
        if not (source or listed):  # EXISTS holds its query without a Subquery
            found.add(id(unwrap(sub)))
    return found


def add_tiebreaks(
    tree: exp.Expr, planned: Collection[int], taken: set[str], dialect: str
) -> exp.Expr:
    """Append a random key to the ORDER BY of each planned query; return the new root.

    The key is `RANDOM()` / `RAND()`, or `NEWID()` on SQL Server, where `RAND()`
    is one value per query. A set operation or a SELECT DISTINCT cannot sort by
    an expression outside its output, so it is wrapped: `SELECT q.a, ... FROM
    (<query>) AS q ORDER BY ..., RANDOM()`, taking over its ORDER BY, LIMIT and
    OFFSET. On SQL Server a sorted subquery needs TOP or OFFSET: one without
    either gets `OFFSET 0 ROWS`. `taken` holds the names the wrapper alias must
    avoid; new aliases are added to it.
    """
    root = tree
    for query in [q for q in tree.find_all(exp.Select, exp.SetOperation) if id(q) in planned]:
        sorted_query: exp.Expr = query
        if isinstance(query, exp.Select) and not query.args.get("distinct"):
            order = query.args.get("order")
            keys = order.expressions if isinstance(order, exp.Order) else []
            query.set("order", exp.Order(expressions=[*keys, _random_key(dialect)]))
        else:
            sorted_query = _wrap(query, _fresh(taken), dialect)
            root = sorted_query if query is tree else root
        if dialect == "tsql" and sorted_query is not root and not _is_cut(sorted_query):
            sorted_query.set("offset", exp.Offset(expression=exp.Literal.number(0)))
    return root


def _is_cut(query: exp.Expr) -> bool:
    return bool(query.args.get("limit") or query.args.get("offset"))


def _wrap(query: exp.Expr, alias: str, dialect: str) -> exp.Select:
    first = branches(query)[0]
    names = [_output_name(p) for p in first.expressions]
    if len({n.name.lower() for n in names}) != len(names):
        raise Rejection(Reason.AMBIGUOUS_COLUMN)
    order = query.args.get("order")
    keys = [
        _outer_key(o, first, names, alias)
        for o in (order.expressions if isinstance(order, exp.Order) else [])
    ]
    limit, offset = query.args.get("limit"), query.args.get("offset")
    for arg in ("order", "limit", "offset"):
        query.set(arg, None)
    hole = exp.Null()
    if query.parent is not None:
        query.replace(hole)
    wrapper = exp.Select(
        expressions=[_column(alias, n) for n in names],
        from_=exp.From(
            this=exp.Subquery(this=query, alias=exp.TableAlias(this=exp.to_identifier(alias)))
        ),
        order=exp.Order(expressions=[*keys, _random_key(dialect)]),
        limit=limit,
        offset=offset,
    )
    if hole.parent is not None:
        hole.replace(wrapper)
    return wrapper


def _outer_key(
    ordered: exp.Ordered, first: exp.Select, names: list[exp.Identifier], alias: str
) -> exp.Ordered:
    # The key as the wrapper sees it: the output column it sorts by.
    key = strip_parens(ordered.this)
    labels = [n.name for n in names]
    if is_position(key):
        index = int(key.name) - 1
    elif isinstance(key, exp.Column) and not key.table and key.name in labels:
        index = labels.index(key.name)
    else:
        index = next((i for i, p in enumerate(first.expressions) if p.unalias() == key), -1)
    if not 0 <= index < len(names):
        raise Rejection(Reason.NODE_NOT_ALLOWED)
    return exp.Ordered(
        this=_column(alias, names[index]),
        desc=ordered.args.get("desc"),
        nulls_first=ordered.args.get("nulls_first"),
    )


def _output_name(proj: exp.Expr) -> exp.Identifier:
    name = proj.args.get("alias") if isinstance(proj, exp.Alias) else proj.this
    # The NULL of an emptied star is refused; `name` is always an Identifier (narrows the type).
    if not isinstance(proj, exp.Alias | exp.Column) or not isinstance(name, exp.Identifier):
        raise Rejection(Reason.AMBIGUOUS_COLUMN)
    return name


def _column(alias: str, name: exp.Identifier) -> exp.Column:
    return exp.Column(this=name.copy(), table=exp.to_identifier(alias))


def _fresh(taken: set[str]) -> str:
    n = 0
    while f"_q{n}" in taken:
        n += 1
    taken.add(f"_q{n}")
    return f"_q{n}"


def _random_key(dialect: str) -> exp.Ordered:
    # SQLite renders `RANDOM() NULLS LAST`; NULLS LAST needs SQLite >= 3.30.
    if dialect == "tsql":  # nulls first is T-SQL's own order: no CASE emulation
        return exp.Ordered(this=exp.Uuid(), nulls_first=True)
    return exp.Ordered(this=exp.Rand())
