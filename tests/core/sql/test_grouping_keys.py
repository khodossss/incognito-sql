"""A column outside GROUP BY is grouped when its table's whole primary key is a key."""

from types import MappingProxyType

import pytest

from incognito_sql.core.config import Limits
from incognito_sql.core.config.row_rules import RowRule
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.allowlist import check_nodes
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.policy import enforce
from incognito_sql.core.sql.resolve import qualify_tree

from .conftest import CATALOG, DECL, DIALECTS

SAFE = Catalog(
    columns=CATALOG.columns,
    keys=MappingProxyType({"people": ("id",), "orders": ("id",)}),
    null_free=frozenset({"people", "orders"}),
)
LOOSE = Catalog(columns=CATALOG.columns, keys=SAFE.keys, null_free=frozenset())
NNA = Reason.NODE_NOT_ALLOWED


def _run(
    sql: str,
    dialect: str,
    catalog: Catalog,
    protection: str = "strict",
    rules: list[RowRule] | None = None,
) -> Reason | None:
    update = {"protection": protection, "dialect": dialect, "row_rules": rules or []}
    decl = DECL.model_copy(update=update)
    try:
        tree = parse(sql, dialect, Limits())
        check_nodes(tree)
        enforce(qualify_tree(tree, catalog, dialect), catalog, decl)
    except Rejection as exc:
        return exc.reason
    return None


KEYED = "SELECT p.id, p.city, count(*) FROM people p JOIN orders o ON o.id = p.id GROUP BY p.id"


@pytest.mark.parametrize("dialect", DIALECTS)
def test_key_groups_its_table(dialect: str) -> None:
    assert _run(KEYED, dialect, SAFE) is None
    assert _run(KEYED + " ORDER BY p.city", dialect, SAFE) is None
    assert _run(KEYED, dialect, CATALOG) == NNA  # no key known


@pytest.mark.parametrize("dialect", DIALECTS)
def test_a_key_that_may_hold_null_is_permissive_only(dialect: str) -> None:
    assert _run(KEYED, dialect, LOOSE) == NNA
    assert _run(KEYED, dialect, LOOSE, "balanced") == NNA
    assert _run(KEYED, dialect, LOOSE, "permissive") is None


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT p.city, count(*) FROM people p JOIN orders o ON o.id = p.id GROUP BY o.id",
        "SELECT o.note, count(*) FROM people p JOIN orders o ON o.id = p.id GROUP BY p.id",
        "SELECT p.city, count(*) FROM people p GROUP BY p.id + 0",
    ],
)
def test_other_keys_do_not_group(sql: str, dialect: str) -> None:
    assert _run(sql, dialect, SAFE) == NNA


@pytest.mark.parametrize("dialect", ["duckdb", "tsql"])
def test_dbms_that_refuse_key_grouping_get_no_relaxation(dialect: str) -> None:
    assert _run(KEYED, dialect, SAFE) == NNA


@pytest.mark.parametrize("dialect", ["sqlite", "postgres", "mysql"])
def test_a_key_a_row_rule_hides_does_not_group(dialect: str) -> None:
    hidden = RowRule(table="people", hide=["id"], where="city = 'Haifa'")
    dropped = RowRule(table="people", hide="*", where="city = 'Haifa'")
    assert _run(KEYED, dialect, SAFE, rules=[hidden]) == NNA  # NULL keys share one group
    assert _run(KEYED, dialect, SAFE, rules=[dropped]) is None  # kept rows keep their key
