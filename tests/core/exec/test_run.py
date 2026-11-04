"""Execution: row cap, empty statement, sanitized database errors."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Self

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError

from incognito_sql.core.config import Limits
from incognito_sql.core.db import make_engine
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.exec.run import Rows, execute
from incognito_sql.core.sql.rewrite import Prepared

CANARY = "Zqcanary"
BAD_COLUMN = "zz_nonexistent_col"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    path = tmp_path / "people.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE people (id INTEGER, full_name TEXT)")
    con.executemany(
        "INSERT INTO people VALUES (?, ?)", [(1, "Ivan Petrov"), (2, "Anna Ivanova"), (3, "Oleg")]
    )
    con.commit()
    con.close()
    eng = make_engine(f"sqlite:///{path}", "sqlite")
    yield eng
    eng.dispose()


def _prepared(sql: str, params: dict[str, object] | None = None) -> Prepared:
    return Prepared(sql=sql, params=params or {}, hidden_count=0, output_classes=[])


def test_returns_columns_and_rows(engine: Engine) -> None:
    out = execute(engine, _prepared("SELECT id, full_name FROM people ORDER BY id"), Limits())
    assert out == Rows(
        columns=["id", "full_name"],
        rows=[(1, "Ivan Petrov"), (2, "Anna Ivanova"), (3, "Oleg")],
        truncated=False,
    )


def test_binds_params(engine: Engine) -> None:
    out = execute(engine, _prepared("SELECT id FROM people WHERE id = :p", {"p": 2}), Limits())
    assert out.rows == [(2,)]


def test_truncates_at_max_rows(engine: Engine) -> None:
    out = execute(engine, _prepared("SELECT id FROM people ORDER BY id"), Limits(max_rows=2))
    assert out.truncated is True
    assert out.rows == [(1,), (2,)]


def test_exact_cap_not_truncated(engine: Engine) -> None:
    out = execute(engine, _prepared("SELECT id FROM people ORDER BY id"), Limits(max_rows=3))
    assert out.truncated is False
    assert len(out.rows) == 3


def test_empty_sql_skips_database() -> None:
    out = execute(None, _prepared(""), Limits())  # type: ignore[arg-type]
    assert out == Rows(columns=[], rows=[], truncated=False)


def test_db_error_is_sanitized(engine: Engine) -> None:
    sql = "SELECT zz_nonexistent_col FROM people WHERE full_name = :p"
    prepared = _prepared(sql, {"p": CANARY})
    with pytest.raises(Rejection) as info:
        execute(engine, prepared, Limits())
    exc = info.value
    assert exc.reason is Reason.DB_ERROR
    assert exc.sqlstate is None
    assert exc.detail is None
    assert exc.__cause__ is None
    assert exc.__context__ is None
    for text in (str(exc), repr(exc), repr(exc.args)):
        assert CANARY not in text
        assert BAD_COLUMN not in text
        assert "SELECT" not in text


class _Diag:
    def __init__(self, message: str) -> None:
        self.message_primary = message


class _FakeOrig(Exception):  # noqa: N818
    def __init__(self, sqlstate: str, message: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate
        self.diag = _Diag(message)


class _FakeEngine:
    def __init__(self, orig: Exception) -> None:
        self.orig = orig

    def connect(self) -> "_FakeEngine":
        return self

    def execution_options(self, **_kw: object) -> "_FakeEngine":
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_a: object) -> None:
        return None

    def execute(self, *_a: object, **_k: object) -> object:
        msg = "SELECT secret [parameters: Zqcanary]"
        raise DBAPIError(msg, {"p": CANARY}, self.orig)


def _run_fake(orig: Exception) -> Rejection:
    prepared = _prepared("SELECT 1", {"p": CANARY})
    with pytest.raises(Rejection) as info:
        execute(_FakeEngine(orig), prepared, Limits())  # type: ignore[arg-type]
    return info.value


def test_postgres_class_42_keeps_scrubbed_detail() -> None:
    msg = f'column "{BAD_COLUMN}" does not exist near {CANARY} tk_abcdefghijklmnop'
    exc = _run_fake(_FakeOrig("42703", msg))
    assert exc.sqlstate == "42703"
    assert exc.detail is None
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert CANARY not in repr(exc.args) + str(exc)


def test_postgres_other_class_has_no_detail() -> None:
    exc = _run_fake(_FakeOrig("22P02", f"invalid input {CANARY}"))
    assert exc.sqlstate == "22P02"
    assert exc.detail is None


def test_orig_without_sqlstate() -> None:
    exc = _run_fake(RuntimeError(CANARY))
    assert exc.sqlstate is None
    assert exc.detail is None


def test_class_42_message_kept_when_clean() -> None:
    exc = _run_fake(_FakeOrig("42703", f'column "{BAD_COLUMN}" does not exist'))
    assert exc.detail == f'column "{BAD_COLUMN}" does not exist'


@pytest.mark.parametrize("message", ["near ZQCANARY here", "xzqcanaryx", "has TK_ABC", "x Tk_y"])
def test_class_42_dropped_on_value_or_token(message: str) -> None:
    exc = _run_fake(_FakeOrig("42601", message))
    assert exc.sqlstate == "42601"
    assert exc.detail is None


def _leaks(exc: BaseException, needle: str) -> bool:
    out: list[str] = []
    tb = exc.__traceback__
    while tb is not None:
        out.extend(repr(v) for v in tb.tb_frame.f_locals.values())
        tb = tb.tb_next
    return needle.lower() in ("\n".join(out) + repr(exc) + str(exc)).lower()


def test_decode_error_leaves_no_raw_data(engine: Engine, tmp_path: Path) -> None:
    con = sqlite3.connect(tmp_path / "people.db")
    con.execute("INSERT INTO people VALUES (9, CAST(X'5a7a64617461ff' AS TEXT))")
    con.commit()
    con.close()
    with pytest.raises(Rejection) as info:
        execute(engine, _prepared("SELECT full_name FROM people WHERE id = 9"), Limits())
    exc = info.value
    assert exc.reason is Reason.DB_ERROR
    leaked = _leaks(exc, "Zzdata")
    assert not leaked
    leaked = _leaks(exc, "utf-8")
    assert not leaked
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]


def test_non_dbapi_exception_is_mapped(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> list[object]:
        msg = "Zqraw failure"
        raise ValueError(msg)

    monkeypatch.setattr("sqlalchemy.engine.cursor.CursorResult.fetchmany", boom)
    with pytest.raises(Rejection) as info:
        execute(engine, _prepared("SELECT id FROM people"), Limits())
    exc = info.value
    assert exc.reason is Reason.DB_ERROR
    assert exc.sqlstate is None
    leaked = _leaks(exc, "Zqraw")
    assert not leaked
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]


def test_pool_released_after_db_error(engine: Engine) -> None:
    with pytest.raises(Rejection):
        execute(engine, _prepared("SELECT zz_bad FROM people"), Limits())
    assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]
