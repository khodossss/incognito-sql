"""The base columns a query names, for the journal: names only, wherever they stand."""

import pytest

from incognito_sql.core.config import Limits
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.origin import read_columns
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.resolve import qualify_tree

from .conftest import CATALOG, DECL

CASES = [
    ("SELECT o.id FROM orders o JOIN people p ON p.id = o.id", ["orders.id", "people.id"]),
    ("SELECT x FROM (SELECT full_name AS x FROM people) d", ["people.full_name"]),
    ("SELECT id FROM people UNION SELECT id FROM orders", ["orders.id", "people.id"]),
    ("SELECT id FROM people ORDER BY full_name", ["people.full_name", "people.id"]),
    # asked about, though never read: the journal says what the query names
    (
        "WITH c AS (SELECT full_name FROM people) SELECT id FROM orders",
        ["orders.id", "people.full_name"],
    ),
    ("SELECT count(*) FROM people WHERE full_name = 'Zqcanary Person'", ["people.full_name"]),
]


def _read(sql: str) -> list[str]:
    tree = qualify_tree(parse(sql, "sqlite", Limits()), CATALOG, "sqlite")
    return read_columns(tree, Lineage(tree, CATALOG, DECL))


@pytest.mark.parametrize(("sql", "expected"), CASES)
def test_read_columns(sql: str, expected: list[str]) -> None:
    assert _read(sql) == expected


def test_a_column_lineage_cannot_trace_is_left_out() -> None:
    sql = "SELECT d.note FROM (SELECT p.* FROM people p JOIN orders o ON o.id = p.id) d"
    assert _read(sql) == ["orders.id", "people.id"]
