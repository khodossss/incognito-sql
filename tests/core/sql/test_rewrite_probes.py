"""Row-order probes: a cut or capped result must not follow the order of names."""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from incognito_sql.core.db import make_engine

from .conftest import PrepareRun

NAMES = [f"Zq Person {i:02d}" for i in range(30)]
RUNS = 25
PROBES = [
    # k-th name alphabetically through a grouped derived table
    (
        "SELECT full_name FROM people WHERE id = (SELECT x.m FROM "
        "(SELECT min(id) AS m FROM people GROUP BY full_name) x LIMIT 1 OFFSET 3)"
    ),
    # a covering index on full_name orders the inner scan by name
    "SELECT full_name FROM people WHERE id IN (SELECT id FROM people LIMIT 1)",
    # the row cap keeps the first rows of whatever order the scan has
    "SELECT full_name FROM people",
    # a scalar subquery is an implicit LIMIT 1 on SQLite
    (
        "SELECT full_name FROM people WHERE id = (SELECT x.m FROM "
        "(SELECT min(id) AS m FROM people GROUP BY full_name) x)"
    ),
    (
        "SELECT full_name FROM people WHERE id = (SELECT x.m FROM "
        "(SELECT min(id) AS m FROM people GROUP BY full_name) x WHERE x.m NOT IN (100, 99))"
    ),
    "SELECT full_name FROM people WHERE id = (SELECT id FROM people)",
    "SELECT count(*) FROM people WHERE id > (SELECT id FROM people)",
    "SELECT CASE WHEN (SELECT id FROM people) > 85 THEN 1 ELSE 0 END AS k FROM people LIMIT 1",
]


@pytest.fixture(params=[False, True], ids=["no-index", "name-index"])
def engine(request: pytest.FixtureRequest, tmp_path: Path) -> Engine:
    path = tmp_path / "probe.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT, phone BIGINT,"
        " city TEXT, notes TEXT)"
    )
    # ids run against name order, so neither order hides the other
    rows = [(100 - i, name, None, "Zqtown", None) for i, name in enumerate(NAMES)]
    con.executemany("INSERT INTO people VALUES (?, ?, ?, ?, ?)", rows)
    if request.param:
        con.execute("CREATE INDEX ix_name ON people (full_name)")
    con.commit()
    con.close()
    return make_engine(f"sqlite:///{path}", "sqlite")


@pytest.mark.parametrize("sql", PROBES)
def test_first_row_does_not_track_name_order(
    prepare_sql: PrepareRun, engine: Engine, sql: str
) -> None:
    p = prepare_sql(sql, "sqlite")
    with engine.connect() as con:
        firsts = {con.execute(text(p.sql), p.params).fetchall()[0][0] for _ in range(RUNS)}
    engine.dispose()
    assert len(firsts) > 1
