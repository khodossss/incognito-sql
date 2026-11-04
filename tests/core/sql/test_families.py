"""Type families: one family per identifier union column, comparisons through every branch."""

import pytest
from sqlglot import exp

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.families import one_family, value_families
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.resolve import qualify_tree

from .conftest import CATALOG, DECL, DIALECTS, PolicyRun, summary

ALL = ["postgres", "sqlite", "mysql", "duckdb", "tsql"]
MIXED_UNIONS = [
    "SELECT phone FROM people UNION ALL SELECT full_name FROM people",
    (
        "SELECT q.x FROM (SELECT phone AS x FROM people WHERE id = 4"
        " UNION ALL SELECT full_name FROM people WHERE id = 4) q"
    ),
    (
        "WITH u AS (SELECT full_name AS x FROM people UNION SELECT phone FROM people)"
        " SELECT COUNT(*) FROM u"
    ),
    (
        "SELECT id FROM people WHERE full_name IN"
        " (SELECT full_name FROM people UNION ALL SELECT phone FROM people)"
    ),
    (
        "SELECT o.id FROM orders o JOIN (SELECT full_name AS x FROM people"
        " UNION ALL SELECT phone FROM people) q ON q.x = o.customer_name"
    ),
    (
        "SELECT full_name, id FROM people UNION SELECT customer_name, id FROM orders"
        " UNION SELECT phone, id FROM people"
    ),
]


@pytest.mark.parametrize("dialect", ALL)
@pytest.mark.parametrize("sql", MIXED_UNIONS)
def test_union_of_two_families_is_refused(policy: PolicyRun, dialect: str, sql: str) -> None:
    assert policy(sql, dialect) is Reason.LITERAL_TYPE_MISMATCH


@pytest.mark.parametrize("dialect", ALL)
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT full_name FROM people UNION SELECT customer_name FROM orders",
        "SELECT full_name FROM people UNION ALL SELECT NULL",
        "SELECT phone FROM people UNION SELECT phone FROM people",
    ],
)
def test_union_of_one_family_passes(policy: PolicyRun, dialect: str, sql: str) -> None:
    assert summary(policy(sql, dialect)) == ([0], 0, 0)


@pytest.mark.parametrize(
    ("sql", "kind"),
    [
        (
            (
                "SELECT q.x FROM (SELECT full_name AS x FROM people"
                " UNION ALL SELECT phone FROM people) AS q"
            ),
            exp.Column,
        ),
        (
            (
                "SELECT id FROM people WHERE full_name IN"
                " (SELECT full_name FROM people UNION ALL SELECT phone FROM people)"
            ),
            exp.Subquery,
        ),
    ],
)
def test_families_of_a_union_value_come_from_every_branch(sql: str, kind: type[exp.Expr]) -> None:
    tree = qualify_tree(parse(sql, "postgres", Limits()), CATALOG, "postgres")
    node = tree.find(kind)
    assert node is not None
    assert value_families(node, Lineage(tree, CATALOG, DECL), CATALOG) == {"character", "integer"}


@pytest.mark.parametrize("dialect", DIALECTS)
def test_scalar_subquery_is_compared_by_its_output(policy: PolicyRun, dialect: str) -> None:
    sql = (
        "SELECT id FROM people WHERE full_name ="
        " (SELECT q.full_name FROM (SELECT * FROM people) q LIMIT 1)"
    )
    assert summary(policy(sql, dialect)) == ([], 0, 0)


def test_unknown_types_never_share_a_family() -> None:
    assert not one_family([{""}, {""}])
    assert one_family([{""}, set()])
    assert one_family([{"DATE"}, {"DATE"}])


@pytest.mark.parametrize("dialect", ["sqlite", "mysql"])
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM orders ORDER BY id OFFSET 1",
        "SELECT n.id FROM (SELECT id FROM orders ORDER BY id OFFSET 1) AS n",
        "SELECT id FROM orders UNION SELECT id FROM people ORDER BY id OFFSET 1",
    ],
)
def test_offset_without_limit_is_refused_at_parse(dialect: str, sql: str) -> None:
    with pytest.raises(Rejection) as raised:
        parse(sql, dialect, Limits())
    assert raised.value.reason is Reason.NODE_NOT_ALLOWED


@pytest.mark.parametrize("dialect", ["postgres", "duckdb"])
def test_offset_without_limit_parses_elsewhere(dialect: str) -> None:
    assert parse("SELECT id FROM orders ORDER BY id OFFSET 1", dialect, Limits()) is not None
