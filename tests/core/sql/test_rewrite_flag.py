"""The random tiebreak passes only the re-check of rewritten SQL; elsewhere it stays closed."""

import pytest
from sqlglot import exp

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.allowlist import check_nodes
from incognito_sql.core.sql.order_keys import check_order_keys
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.policy import enforce
from incognito_sql.core.sql.resolve import qualify_tree

from .conftest import CATALOG, DECL, DIALECTS


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT full_name FROM people ORDER BY RANDOM()",
        "SELECT full_name FROM people ORDER BY id, RANDOM() NULLS LAST",
    ],
)
def test_tiebreak_passes_only_the_recheck(dialect: str, sql: str) -> None:
    tree = parse(sql, dialect, Limits())
    with pytest.raises(Rejection):
        check_nodes(tree)
    with pytest.raises(Rejection):
        check_order_keys(tree)
    with pytest.raises(Rejection):
        qualify_tree(tree, CATALOG, dialect)
    check_nodes(tree, allow_placeholders=True)
    qualified = qualify_tree(tree, CATALOG, dialect, allow_rewrite=True)
    with pytest.raises(Rejection):
        enforce(qualified, CATALOG, DECL)
    assert enforce(qualified, CATALOG, DECL, allow_placeholders=True).pii_outputs == [0]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT RANDOM() FROM people",
        "SELECT id FROM people WHERE RANDOM() = 1",
        "SELECT id FROM people ORDER BY (RANDOM())",
        "SELECT id FROM people ORDER BY RANDOM() + 1",
    ],
)
def test_random_elsewhere_stays_closed(sql: str) -> None:
    tree = parse(sql, "postgres", Limits())
    with pytest.raises(Rejection) as exc:
        check_nodes(tree, allow_placeholders=True)
    assert exc.value.reason is Reason.NODE_NOT_ALLOWED


def test_seeded_random_stays_closed() -> None:
    tree = parse("SELECT id FROM people ORDER BY RANDOM()", "postgres", Limits())
    rand = tree.find(exp.Rand)
    assert rand is not None
    rand.set("this", exp.Literal.number(1))
    with pytest.raises(Rejection):
        check_nodes(tree, allow_placeholders=True)
    with pytest.raises(Rejection):
        check_order_keys(tree, allow_rewrite=True)
