"""Lineage refuses what it cannot trace, even on trees that skipped qualify."""

import pytest
import sqlglot
from sqlglot import exp

from incognito_sql.core.config import ColumnClass
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.colref import ColumnRef, rank
from incognito_sql.core.sql.lineage import Lineage

from .conftest import CATALOG, DECL, DIALECTS, Outcome, PolicyRun, summary

CASES: list[tuple[str, Outcome]] = [
    ("SELECT d.x FROM (SELECT id AS x, full_name AS x FROM people) d", Reason.AMBIGUOUS_COLUMN),
    ("SELECT id FROM people UNION SELECT id FROM orders ORDER BY nope", Reason.UNKNOWN_COLUMN),
    (
        (
            "SELECT full_name FROM people UNION SELECT customer_name FROM orders "
            "ORDER BY customer_name"
        ),
        Reason.UNKNOWN_COLUMN,
    ),
    # `t.*` in a derived table reads only `t`; a name no star carries is untraceable
    ("SELECT d.id FROM (SELECT p.* FROM people p JOIN orders o ON o.id = p.id) d", ([], 0, 0)),
    (
        "SELECT d.note FROM (SELECT p.* FROM people p JOIN orders o ON o.id = p.id) d",
        Reason.UNKNOWN_COLUMN,
    ),
    ("SELECT d.nope FROM (SELECT * FROM people) d", Reason.UNKNOWN_COLUMN),
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "expected"), CASES)
def test_untraceable(policy: PolicyRun, dialect: str, sql: str, expected: Outcome) -> None:
    assert summary(policy(sql, dialect)) == expected


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM people",  # unqualified outside ORDER BY
        "SELECT q.id FROM people p",  # no such source
        "SELECT p.nope FROM people p",  # no such column
        "SELECT n.id FROM nosuch n",  # no such table
    ],
)
def test_raw_tree_is_refused(sql: str) -> None:
    tree = sqlglot.parse_one(sql, read="postgres")
    col = tree.find(exp.Column)
    assert col is not None
    with pytest.raises(Rejection) as info:
        Lineage(tree, CATALOG, DECL).source_of(col)
    assert info.value.reason is Reason.UNKNOWN_COLUMN


def test_detached_column_is_refused() -> None:
    tree = sqlglot.parse_one("SELECT 1", read="postgres")
    with pytest.raises(Rejection) as info:
        Lineage(tree, CATALOG, DECL).source_of(exp.column("id", table="people"))
    assert info.value.reason is Reason.UNKNOWN_COLUMN


def test_rank_orders_hidden_first() -> None:
    order = [ColumnClass.OPEN, ColumnClass.QUASI, ColumnClass.IDENTIFIER, None]
    assert [rank(c) for c in order] == [0, 1, 2, 3]
    assert rank(ColumnClass.SECRET) == rank(ColumnClass.FREE_TEXT) == rank(None)
    assert ColumnRef("people", "notes", None).cls is None
