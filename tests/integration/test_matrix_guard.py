"""On every DBMS the engine cannot write, and a database error leaves only reason and state."""

import json

import pytest
from sqlalchemy import create_engine, text

from bench.dbms import Database
from incognito_sql.core.config import Limits
from incognito_sql.core.db import make_engine
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.exec.run import execute
from incognito_sql.core.pipeline import Gateway
from incognito_sql.core.sql.rewrite import Prepared

from .conftest import Field
from .test_matrix import rows

pytestmark = pytest.mark.integration
WRITES = [
    "INSERT INTO staff (id, login) VALUES (2, 'Zqwritten')",
    "UPDATE staff SET login = 'Zqwritten'",
    "CREATE TABLE zqnew (id INTEGER)",
]
# SQL Server has no read-only session: there the reader login is the only guard.
SESSION_GUARDED = {"postgres", "mysql", "sqlite", "duckdb"}


def _write_fails(dsn: str, dialect: str, sql: str) -> bool:
    engine = make_engine(dsn, dialect)
    try:
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
    except Exception:  # noqa: BLE001 -- any refusal of the DBMS will do
        return True
    finally:
        engine.dispose()
    return False


@pytest.mark.parametrize("sql", WRITES[:2])
def test_the_writes_work_for_a_plain_admin_engine(backend: Database, sql: str) -> None:
    # The falsifier of the tests below: the statements are valid, only the guards stop them.
    engine = create_engine(backend.admin)
    try:
        with engine.connect() as conn:
            assert conn.execute(text(sql)).rowcount >= 1
            conn.rollback()
    finally:
        engine.dispose()


@pytest.mark.parametrize("sql", WRITES)
def test_the_reader_engine_cannot_write(backend: Database, sql: str) -> None:
    assert _write_fails(backend.url, backend.dialect, sql)


@pytest.mark.parametrize("sql", WRITES)
def test_the_session_is_read_only_even_for_an_admin(backend: Database, sql: str) -> None:
    if backend.dialect not in SESSION_GUARDED:
        pytest.skip("no read-only session on this DBMS")
    assert _write_fails(backend.admin, backend.dialect, sql)


def test_a_database_error_is_a_reason_and_a_state(field: Field, gateway: Gateway) -> None:
    # More than one row from a value subquery: an error on every DBMS but SQLite.
    sql = field.sql("SELECT id, (SELECT customer_name FROM orders) AS c FROM people")
    out = gateway.query(sql, "c1")
    if field.backend.dialect == "sqlite":
        assert "rows" in out
        return
    expected_state = "21000" if field.backend.dialect in {"postgres", "mysql"} else None
    assert out == {"error": Reason.DB_ERROR.value, "sqlstate": expected_state}
    assert "zqcanary" not in json.dumps(out).casefold()


def test_class_42_detail_drops_bound_values(field: Field) -> None:
    if field.backend.dialect != "postgres":
        pytest.skip("only Postgres reports SQLSTATE with a primary message")
    engine = make_engine(field.backend.url, "postgres")
    try:
        prepared = Prepared("SELECT CAST(:p0 AS regclass)", {"p0": "Zqcanary"}, 0, [None])
        with pytest.raises(Rejection) as raised:
            execute(engine, prepared, Limits())
        assert (raised.value.sqlstate, raised.value.detail) == ("42P01", None)
        plain = Prepared("SELECT nope FROM people WHERE id = :p0", {"p0": 1}, 0, [None])
        with pytest.raises(Rejection) as raised:
            execute(engine, plain, Limits())
        assert raised.value.sqlstate == "42703"
        assert raised.value.detail == 'column "nope" does not exist'
    finally:
        engine.dispose()


def test_one_value_in_two_type_contexts(field: Field, gateway: Gateway) -> None:
    # One bind name for '1' compared to an integer and to a text column: Postgres
    # types the parameter once and refuses the other use; nothing of the value leaks.
    sql = field.sql("SELECT id FROM people WHERE id = '1' OR city = '1'")
    out = gateway.query(sql, "c1")
    if field.backend.dialect != "postgres":
        assert rows(out) == [[1]]
        return
    assert (out["error"], str(out["sqlstate"])[:2]) == ("db_error", "42")
    assert "1" not in str(out.get("detail", ""))
