"""SQLite and DuckDB get a statement deadline: a long query is cut, the next one runs."""

import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from incognito_sql.core.db import make_engine

LONG = {
    "sqlite": (
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 200000000)"
        " SELECT count(*) FROM c"
    ),
    "duckdb": "SELECT count(*) FROM range(100000000000) AS a",
}


@pytest.fixture(params=["sqlite", "duckdb"])
def opened(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[tuple[str, Engine]]:
    dialect = str(request.param)
    path = tmp_path / f"d.{dialect}"
    if dialect == "sqlite":
        sqlite3.connect(path).close()
    else:
        duckdb.connect(str(path)).close()
    eng = make_engine(f"{dialect}:///{path.as_posix()}", dialect, statement_timeout_ms=300)
    yield dialect, eng
    eng.dispose()


def test_a_long_statement_is_cut_and_the_next_one_runs(opened: tuple[str, Engine]) -> None:
    dialect, engine = opened
    started = time.monotonic()
    with pytest.raises(DBAPIError), engine.connect() as conn:
        conn.execute(text(LONG[dialect])).fetchall()
    assert time.monotonic() - started < 5
    with engine.connect() as conn:
        conn.execute(text("SELECT 1")).fetchall()
        time.sleep(0.5)  # past the deadline of the statement before: no late cut
        assert conn.execute(text("SELECT 2")).scalar() == 2
