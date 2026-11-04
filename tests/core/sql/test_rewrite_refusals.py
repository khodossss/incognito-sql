"""Queries whose result follows the scan order are refused before they run."""

import sqlite3
from pathlib import Path

import pytest

from incognito_sql.core.errors import Reason, Rejection

from .conftest import PrepareRun

NAMES = [f"Zq Person {i:02d}" for i in range(30)]
PROBES = [
    # the aggregate reads only an outer column, so SQLite aggregates the outer query
    ("SELECT (SELECT count((SELECT p.id)) FROM orders o WHERE o.id = 1) AS c, p.id FROM people p"),
    # SQLite reads the alias `x` as p.id, so count aggregates the outer query
    (
        "SELECT (SELECT p.id AS x FROM orders o WHERE o.id = 1 ORDER BY count(x)) AS c, "
        "p.full_name FROM people p"
    ),
    # the order of additions decides whether the float sum overflows
    (
        "SELECT sum(d.x) FROM (SELECT CASE WHEN id = 100 THEN 1e308 WHEN id = 99 THEN 1e308 "
        "WHEN id = 71 THEN -1e308 ELSE 0 END AS x FROM people) d"
    ),
]


def _run_raw(path: Path, sql: str, *, index: bool) -> list[tuple[object, ...]]:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT, phone BIGINT,"
        " city TEXT, notes TEXT)"
    )
    con.execute("CREATE TABLE orders (id INTEGER, customer_name TEXT, note TEXT, amount NUMERIC)")
    # ids run against name order, so an index on names reverses the scan
    rows = [(100 - i, name, None, "Zqtown", None) for i, name in enumerate(NAMES)]
    con.executemany("INSERT INTO people VALUES (?, ?, ?, ?, ?)", rows)
    con.execute("INSERT INTO orders VALUES (1, NULL, NULL, 5)")
    if index:
        con.execute("CREATE INDEX ix ON people (full_name)")
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


@pytest.mark.parametrize("sql", PROBES)
def test_scan_order_query_is_refused(prepare_sql: PrepareRun, tmp_path: Path, sql: str) -> None:
    plain = _run_raw(tmp_path / "plain.db", sql, index=False)
    indexed = _run_raw(tmp_path / "indexed.db", sql, index=True)
    assert plain != indexed  # run as written, the result follows the index
    with pytest.raises(Rejection) as caught:
        prepare_sql(sql, "sqlite")
    assert caught.value.reason is Reason.NODE_NOT_ALLOWED
