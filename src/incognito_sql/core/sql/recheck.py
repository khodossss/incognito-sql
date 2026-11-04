"""Check SQL the server rewrote exactly as if the model had sent it, and more strictly."""

import re
from collections import Counter

from sqlalchemy import text
from sqlalchemy.dialects import sqlite
from sqlglot import exp

from incognito_sql.core.config import Declaration
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.allowlist import check_nodes
from incognito_sql.core.sql.bind import is_syntax
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.policy import enforce
from incognito_sql.core.sql.resolve import qualify_tree

PLAIN_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A table or column of the catalog may also hold spaces, parentheses and hyphens: none
# is a bind mark (`:`, `%`, `?`, `$`, `@`) or a quote, and `--` fails the comment check.
# A name derived from a value's text is not a catalog name: the rewrite renames it plain.
SCHEMA_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_ ()-]*")
# The rewrite grows a query by the stored forms of its compared items; that growth is
# bounded before binding, on the model's own items, so no size limit may refuse it here
# (a refusal would tell how many forms are stored).
_GROWN = {"max_sql_chars": 1 << 30, "max_ast_nodes": 1 << 30, "max_in_items": 1 << 30}


def recheck(sql: str, params: dict[str, object], catalog: Catalog, decl: Declaration) -> None:
    """Run the whole chain on `sql`; then demand plain names, no values, exact binds.

    Every identifier must be a plain name (a quoted one may carry a bind mark
    that a driver would fill in); no value literal and no comment marker may be
    left; the bind occurrences the tree holds and those SQLAlchemy `text()` finds
    must be the same multiset, over exactly the names of `params`. Size limits
    other than joins are not applied again. Raises Rejection.
    """
    tree = parse(sql, decl.dialect, decl.limits.model_copy(update=_GROWN))
    check_nodes(tree, allow_placeholders=True)
    qualified = qualify_tree(tree, catalog, decl.dialect, allow_rewrite=True)
    enforce(qualified, catalog, decl, allow_placeholders=True)
    names = [i.name for i in tree.find_all(exp.Identifier)]
    placed = Counter(p.name for p in tree.find_all(exp.Placeholder))
    # A positional compile lists every bind occurrence in order.
    bound = Counter(text(sql).compile(dialect=sqlite.dialect()).positiontup or [])
    values = [lit for lit in tree.find_all(exp.Literal) if not is_syntax(lit)]
    if (
        "--" in sql
        or "/*" in sql
        or values
        or not all(_named(n, catalog) for n in names)
        or placed != bound
        or set(placed) != set(params)
    ):
        raise Rejection(Reason.NODE_NOT_ALLOWED)


def _named(name: str, catalog: Catalog) -> bool:
    if PLAIN_NAME.fullmatch(name):
        return True
    if not SCHEMA_NAME.fullmatch(name):
        return False
    folded = name.casefold()
    return any(
        t.casefold() == folded or any(c.casefold() == folded for c in cols)
        for t, cols in catalog.columns.items()
    )
