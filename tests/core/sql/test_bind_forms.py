"""Strict checks of dates, moments, UUIDs, booleans and text bound against an identifier."""

import pytest

from incognito_sql.core.sql.bind_domain import Domain
from incognito_sql.core.sql.bind_forms import Booleans, Dates, Nothing, Stamps, Texts, Uuids
from incognito_sql.core.sql.bind_type import bind_domain

LEGACY = bind_domain("DATETIME", "tsql")
NAIVE, AWARE = Stamps(zone=False), Stamps(zone=True)
UUID = "6f9619ff-8b86-d011-b42d-00c04fc964ff"

CHECKS: list[tuple[Domain, str, object]] = [
    (Dates(), "2020-01-01", "2020-01-01"),
    (Dates(), "2020-13-45", None),
    (Dates(), "0000-01-01", None),
    (Dates(), "2020-1-1", None),
    (Dates(), "not a date", None),
    (NAIVE, "2020-01-01T12:00:00.123456", "2020-01-01 12:00:00.123456"),
    (NAIVE, "9999-12-31 23:59:59", "9999-12-31 23:59:59"),
    (NAIVE, "0001-01-01 00:00:00", "0001-01-01 00:00:00"),  # the first moment itself
    (NAIVE, "9999-12-31 23:59:59.5", None),  # may round past the last moment
    (NAIVE, "2020-01-01 24:00:00", None),
    (NAIVE, "2020-01-01 00:00:00+00:00", None),
    (NAIVE, "2020-01-01", None),
    (AWARE, "2020-01-01 00:00:00+14:00", "2020-01-01 00:00:00+14:00"),
    (AWARE, "2020-01-01 00:00:00", None),
    (AWARE, "2020-01-01 00:00:00+15:00", None),
    (AWARE, "0001-01-01 00:00:00+05:00", None),  # before year 1 in UTC
    (AWARE, "9999-12-31 20:00:00-05:00", None),  # after year 9999 in UTC
    (LEGACY, "2020-01-01 12:00:00.123000", "2020-01-01T12:00:00.123"),
    (LEGACY, "2020-01-01 12:00:00.123456", None),
    (LEGACY, "1700-01-01 00:00:00", None),
    (LEGACY, "1753-01-01 00:00:00.000", "1753-01-01T00:00:00.000"),
    (Uuids(), UUID.upper(), UUID),
    (Uuids(), UUID.replace("-", ""), None),
    (Uuids(), "{" + UUID + "}", None),
    (Booleans(), "True", True),
    (Booleans(), "false", False),
    (Booleans(), "t", None),
    (Booleans(), "1", None),
    (Texts(no_nul=True), "a\0b", None),
    (Texts(no_nul=True), "Ivan Petrov", "Ivan Petrov"),
    (Texts(), "a\0b", "a\0b"),
    (Nothing(), "5", None),
]


@pytest.mark.parametrize(("domain", "raw", "expected"), CHECKS)
def test_check_keeps_only_forms_the_type_holds(domain: Domain, raw: str, expected: object) -> None:
    found = domain.check(raw)
    assert found == expected
    assert type(found) is type(expected)


@pytest.mark.parametrize(
    ("dialect", "column_type", "raw", "expected"),
    [
        ("tsql", "DATETIME", "2020-01-01 12:00:00.123", "2020-01-01T12:00:00.123"),
        ("tsql", "DATETIME", "1700-01-01 00:00:00", None),
        ("tsql", "DATETIME2", "1700-01-01 00:00:00", "1700-01-01 00:00:00"),
        ("mysql", "DATETIME", "1700-01-01 00:00:00", "1700-01-01 00:00:00"),
    ],
)
def test_only_tsql_datetime_gets_the_legacy_check(
    dialect: str, column_type: str, raw: str, expected: str | None
) -> None:
    assert bind_domain(column_type, dialect).check(raw) == expected
