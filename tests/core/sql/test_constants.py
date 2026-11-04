"""Constants the server can tell never fail, and the ones that may."""

import pytest
import sqlglot

from incognito_sql.core.sql.constants import safe_constant


@pytest.mark.parametrize(
    "sql",
    [
        "-1",
        "2 + 1",
        "10 / 2",
        "(3 - 1) * 2",
        "1.5",
        "2147483647 - 1",
        "CAST('x' AS TEXT)",
        "CAST(5 AS VARCHAR(10))",
        "CAST('2020-01-31' AS DATE)",
    ],
)
def test_a_constant_that_never_fails(sql: str) -> None:
    assert safe_constant(sqlglot.parse_one(sql))


@pytest.mark.parametrize(
    "sql",
    [
        "1 / 0",
        "1 / (2 - 2)",
        "2147483647 + 1",
        "100000 * 100000",
        "9223372036854775807 * 2 / 4",
        "CAST('5' AS INTEGER)",
        "CAST('5.0' AS INTEGER)",
        "CAST('1e5' AS INTEGER)",
        "CAST('300' AS TINYINT)",
        "CAST('12345' AS DECIMAL(3, 1))",
        "CAST('2020-02-30' AS DATE)",
        "CAST('2020-1-5' AS DATE)",
        "ABS(-1)",
    ],
)
def test_a_constant_that_may_fail(sql: str) -> None:
    assert not safe_constant(sqlglot.parse_one(sql))
