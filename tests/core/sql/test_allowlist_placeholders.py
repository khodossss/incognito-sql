import pytest

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.allowlist import check_nodes
from incognito_sql.core.sql.parse import parse


def decide(sql: str, dialect: str, *, allow_placeholders: bool = False) -> Reason | None:
    try:
        check_nodes(parse(sql, dialect, Limits()), allow_placeholders=allow_placeholders)
    except Rejection as exc:
        return exc.reason
    return None


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("postgres", "SELECT :p0 FROM people WHERE name = :p0"),
        ("postgres", "SELECT a FROM people WHERE a = %(p0)s"),
        ("postgres", "SELECT a FROM people WHERE a = %s"),
        ("postgres", "SELECT a FROM people WHERE a = ?"),
        ("postgres", "SELECT a FROM people WHERE a = $1"),
        ("postgres", "SELECT a FROM people WHERE a = $x"),
        ("sqlite", "SELECT a FROM people WHERE a = :p0"),
        ("sqlite", "SELECT a FROM people WHERE a = $x"),
        ("sqlite", "SELECT $x FROM people"),
        ("sqlite", "SELECT a FROM people WHERE a = ?"),
        ("sqlite", "SELECT a FROM people WHERE a = @x"),
        ("mysql", "SELECT a FROM people WHERE a = :p0"),
        ("mysql", "SELECT a FROM people WHERE a = ?"),
        ("mysql", "SELECT a FROM people WHERE a = @x"),
    ],
)
def test_model_sent_placeholders_are_rejected(dialect: str, sql: str) -> None:
    assert decide(sql, dialect) == Reason.NODE_NOT_ALLOWED


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("postgres", "SELECT a FROM people WHERE a = %(p0)s"),
        ("sqlite", "SELECT a FROM people WHERE a = :p0"),
        ("mysql", "SELECT a FROM people WHERE a IN (:p0, :p1)"),
    ],
)
def test_placeholders_pass_when_allowed(dialect: str, sql: str) -> None:
    assert decide(sql, dialect, allow_placeholders=True) is None


def test_tiebreak_sort_key_does_not_end_the_check() -> None:
    sql = "SELECT a FROM people WHERE a = (SELECT pg_sleep(1)) ORDER BY RANDOM()"
    assert decide(sql, "postgres", allow_placeholders=True) == Reason.NODE_NOT_ALLOWED


def test_quoted_dollar_name_is_a_column() -> None:
    assert decide('SELECT "$x" FROM people', "sqlite") is None


def test_sqlite_not_indexed_is_rejected() -> None:
    assert decide("SELECT a FROM people NOT INDEXED", "sqlite") == Reason.NODE_NOT_ALLOWED
