"""check_order_keys on its own: every key of every query, positions beside a star."""

import pytest

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.order_keys import check_order_keys
from incognito_sql.core.sql.parse import parse


def _check(sql: str, *, allow_rewrite: bool = False) -> Reason | None:
    try:
        check_order_keys(parse(sql, "postgres", Limits()), allow_rewrite=allow_rewrite)
    except Rejection as exc:
        return exc.reason
    return None


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM people ORDER BY 1, upper(city)",  # a key after a position
        "SELECT *, id FROM people GROUP BY 2",
        "SELECT *, id FROM people GROUP BY (2)",
        "SELECT id FROM people p ORDER BY p.*",
        "SELECT city FROM people p GROUP BY city ORDER BY count(p.*)",
        "SELECT city FROM people GROUP BY city ORDER BY count(DISTINCT id, city)",
    ],
)
def test_key_shape_is_refused(sql: str) -> None:
    assert _check(sql) is Reason.NODE_NOT_ALLOWED


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, city FROM people ORDER BY 1, city",
        "SELECT id FROM people GROUP BY 1",
        "SELECT city FROM people GROUP BY city ORDER BY count(DISTINCT id)",
    ],
)
def test_key_shape_passes(sql: str) -> None:
    assert _check(sql) is None


def test_keys_after_a_tiebreak_are_still_checked() -> None:
    sql = (
        "SELECT d.id FROM (SELECT id FROM people ORDER BY upper(city) LIMIT 2) AS d "
        "ORDER BY RANDOM()"
    )
    assert _check(sql, allow_rewrite=True) is Reason.NODE_NOT_ALLOWED
    assert _check("SELECT id FROM people ORDER BY RANDOM()", allow_rewrite=True) is None
