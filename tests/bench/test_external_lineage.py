"""Which answer columns of a reference query show a hidden column."""

import pytest

from bench.external.lineage import shape

SCHEMA = {
    "People": {"Id": "INTEGER", "Full_Name": "TEXT", "City": "TEXT"},
    "orders": {"id": "INTEGER", "person_id": "INTEGER", "total": "REAL"},
}
HIDDEN = {("people", "full_name"), ("orders", "total")}


@pytest.mark.parametrize(
    ("sql", "opaque"),
    [
        ("SELECT full_name, city FROM people", {0}),
        ("SELECT p.FULL_NAME AS who, count(*) FROM People AS p GROUP BY p.full_name", {0}),
        ("SELECT max(full_name), min(city) FROM people", {0}),
        ("SELECT count(full_name), length(full_name) FROM people", set()),
        ("SELECT x.n FROM (SELECT full_name AS n FROM people) AS x", {0}),
        ("WITH c AS (SELECT full_name FROM people) SELECT full_name FROM c", {0}),
        ("SELECT * FROM people", {1}),
        ("SELECT city FROM people UNION SELECT full_name FROM people", {0}),
        ("SELECT o.id, o.total FROM orders o JOIN people p ON p.id = o.person_id", {1}),
        ("SELECT nonsense(", set()),
    ],
)
def test_opaque_columns(sql: str, opaque: set[int]) -> None:
    assert shape(sql, SCHEMA, HIDDEN)[0] == opaque


@pytest.mark.parametrize(
    ("sql", "ordered"),
    [
        ("SELECT city FROM people ORDER BY city", True),
        ("SELECT city FROM (SELECT city FROM people ORDER BY city) AS t", False),
        ("SELECT city FROM people", False),
        ("SELECT city FROM people UNION SELECT city FROM people ORDER BY 1", True),
    ],
)
def test_ordered_only_by_the_outermost_query(sql: str, *, ordered: bool) -> None:
    assert shape(sql, SCHEMA, HIDDEN)[1] is ordered
