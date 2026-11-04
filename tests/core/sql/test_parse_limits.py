import subprocess
import sys

import pytest

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.parse import parse


def decide(sql: str, limits: Limits) -> Reason | None:
    try:
        parse(sql, "postgres", limits)
    except Rejection as exc:
        return exc.reason
    return None


def test_sql_chars_limit_boundary() -> None:
    sql = "SELECT 1"
    assert decide(sql, Limits(max_sql_chars=len(sql))) is None
    assert decide(sql, Limits(max_sql_chars=len(sql) - 1)) == Reason.LIMIT_EXCEEDED


def test_sql_chars_checked_before_parsing() -> None:
    garbage = "SELECT ((((("
    assert decide(garbage, Limits(max_sql_chars=5)) == Reason.LIMIT_EXCEEDED


def test_ast_nodes_limit_boundary() -> None:
    sql = "SELECT a FROM t"  # Select, Column, Identifier, From, Table, Identifier
    assert decide(sql, Limits(max_ast_nodes=6)) is None
    assert decide(sql, Limits(max_ast_nodes=5)) == Reason.LIMIT_EXCEEDED


def test_joins_limit_boundary() -> None:
    sql = "SELECT a FROM t JOIN u ON t.a = u.a JOIN (SELECT a FROM v JOIN w ON 1 = 1) s ON 1 = 1"
    assert decide(sql, Limits(max_joins=3)) is None
    assert decide(sql, Limits(max_joins=2)) == Reason.LIMIT_EXCEEDED


def test_in_items_limit_boundary() -> None:
    sql = "SELECT a FROM t WHERE a IN (1, 2, 3) OR b IN (SELECT c FROM u WHERE c IN (4, 5))"
    assert decide(sql, Limits(max_in_items=3)) is None
    assert decide(sql, Limits(max_in_items=2)) == Reason.LIMIT_EXCEEDED


def test_rejection_text_is_only_the_reason() -> None:
    with pytest.raises(Rejection) as info:
        parse("SELECT 'Zqsecret", "postgres", Limits())
    assert str(info.value) == "parse_error"
    assert info.value.sqlstate is None
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


def test_rejection_carries_sqlstate() -> None:
    exc = Rejection(Reason.DB_ERROR, sqlstate="57014")
    assert (exc.reason, exc.sqlstate, str(exc)) == (Reason.DB_ERROR, "57014", "db_error")


def test_reason_catalog() -> None:
    names = {
        "PARSE_ERROR",
        "MULTIPLE_STATEMENTS",
        "LIMIT_EXCEEDED",
        "NODE_NOT_ALLOWED",
        "UNKNOWN_COLUMN",
        "AMBIGUOUS_COLUMN",
        "HIDDEN_COLUMN",
        "PII_OPERATION",
        "PII_JOIN_WITH_OPEN",
        "LITERAL_TYPE_MISMATCH",
        "INVALID_TOKEN",
        "LITERAL_BUDGET",
        "SYSTEM_CATALOG",
        "DB_ERROR",
    }
    assert names <= {r.name for r in Reason}
    assert all(r.value == r.name.lower() for r in Reason)


def test_unknown_dialect_is_a_config_error() -> None:
    with pytest.raises(ValueError, match="nosuchdialect"):
        parse("SELECT 1", "nosuchdialect", Limits())


# pytest attaches its log capture to every logger, so the carrier is checked in a
# fresh process: what the server would print to stderr.
_PROBE = """
from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Rejection
from incognito_sql.core.sql.parse import parse
for sql in ["EXPLAIN SELECT 'Zqcanary'", "SELECT 'Zqcanary' FROM {:1}"]:
    try:
        parse(sql, 'postgres', Limits())
    except Rejection:
        pass
"""


def test_parser_writes_no_sql_to_stderr() -> None:
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=True
    )
    assert "Zqcanary" not in done.stdout + done.stderr
