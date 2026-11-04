"""Where a star may stand: a top-level projection item, or COUNT(*)."""

from sqlglot import exp

from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.shape import is_star


def check_star_places(tree: exp.Expr) -> None:
    """Refuse a `*` / `t.*` anywhere but a bare projection item or a bare COUNT(*).

    Elsewhere (in an expression, a predicate, GROUP BY, parentheses, under an
    alias, `COUNT(t.*)`, `COUNT(DISTINCT *)`) PostgreSQL reads `t.*` as the whole
    row. Raises Rejection(NODE_NOT_ALLOWED).
    """
    for node in tree.find_all(exp.Star, exp.Column):
        if not is_star(node) or isinstance(node.parent, exp.Column):
            continue  # a plain column, or the Star inside `t.*` (checked as the Column)
        projection = isinstance(node.parent, exp.Select) and node.arg_key == "expressions"
        count_all = (
            isinstance(node, exp.Star)
            and isinstance(node.parent, exp.Count)
            and node.arg_key == "this"
        )
        if not (projection or count_all):
            raise Rejection(Reason.NODE_NOT_ALLOWED)
