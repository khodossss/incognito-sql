"""SQL Server: the random key is NEWID() (RAND() is one value per query), sorted subqueries
get OFFSET 0 ROWS, and the model itself may write neither."""

import pytest

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.allowlist import check_nodes
from incognito_sql.core.sql.parse import parse

from .conftest import DECL, PrepareRun

# DISTINCT over open text: strict refuses it on SQL Server (equal spellings).
BALANCED = DECL.model_copy(update={"protection": "balanced"})


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT TOP 2 id FROM people ORDER BY id", "ORDER BY id, NEWID()"),
        ("SELECT id FROM people", "FROM people ORDER BY NEWID()"),
        (
            "SELECT id, (SELECT MAX(id) FROM people) AS m FROM people",
            "(SELECT MAX(people.id) AS _col_0 FROM people ORDER BY NEWID() OFFSET 0 ROWS) AS m",
        ),
        (
            "SELECT id, (SELECT DISTINCT city FROM people WHERE id = 1) AS c FROM people",
            "AS _q0 ORDER BY NEWID() OFFSET 0 ROWS) AS c",
        ),
        (
            "SELECT id FROM people WHERE id IN (SELECT TOP 1 id FROM people)",
            "(SELECT TOP 1 people.id AS id FROM people ORDER BY NEWID())",
        ),
        ("SELECT id FROM people ORDER BY id OFFSET 1 ROWS", "ORDER BY id, NEWID() OFFSET 1 ROWS"),
    ],
)
def test_tsql_random_key(prepare_sql: PrepareRun, sql: str, expected: str) -> None:
    out = prepare_sql(sql, "tsql", BALANCED).sql
    assert expected in out
    assert "RAND()" not in out


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM people ORDER BY NEWID()",
        "SELECT id FROM people ORDER BY id OFFSET 1 ROWS FETCH NEXT 2 ROWS ONLY",
    ],
)
def test_tsql_model_cannot_write_them(sql: str) -> None:
    with pytest.raises(Rejection) as raised:
        check_nodes(parse(sql, "tsql", Limits()))
    assert raised.value.reason is Reason.NODE_NOT_ALLOWED
