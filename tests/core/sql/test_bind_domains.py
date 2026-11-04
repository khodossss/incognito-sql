"""Strict checks of numbers bound against an identifier, and the check each type gets."""

from decimal import Decimal

import pytest

from incognito_sql.core.sql.bind_domain import Decimals, Domain, Integers, Money
from incognito_sql.core.sql.bind_forms import Booleans, Dates, Nothing, Stamps, Texts, Uuids
from incognito_sql.core.sql.bind_type import DOUBLE, INT64, SINGLE, bind_domain

U64 = Integers(0, 1 << 64)
PG_NUMERIC = Decimals(131072 + 16383, 16383, pad=False)
PG_MONEY = bind_domain("MONEY", "postgres")
TSQL_MONEY = bind_domain("MONEY", "tsql")
SMALLMONEY = bind_domain("SMALLMONEY", "tsql")
LEGACY = bind_domain("DATETIME", "tsql")
NAIVE, AWARE = Stamps(zone=False), Stamps(zone=True)
UUID = "6f9619ff-8b86-d011-b42d-00c04fc964ff"

CHECKS: list[tuple[Domain, str, object]] = [
    (U64, "5", 5),
    (U64, "18446744073709551615", (1 << 64) - 1),
    (U64, "18446744073709551616", None),
    (U64, "-5", None),
    (U64, "5.0", 5),
    (U64, "5.5", None),
    (U64, "1e3", 1000),
    (U64, "1e400", None),
    (U64, " 5", None),
    (U64, "5_0", None),
    (U64, "NaN", None),
    (U64, "inf", None),
    (INT64, "9223372036854775807", (1 << 63) - 1),
    (INT64, "9223372036854775808", None),
    (INT64, "-9223372036854775808", -(1 << 63)),
    (Decimals(10, 0), "5.00", Decimal(5)),
    (Decimals(10, 0), "5.50", None),
    (Decimals(10, 0), "9999999999", Decimal(9999999999)),
    (Decimals(10, 0), "10000000000", None),
    (Decimals(10, 0), "1e3", Decimal(1000)),
    (Decimals(10, 2), ".5", Decimal("0.50")),
    (Decimals(10, 2), "5.123", None),
    (Decimals(10, 2), "12345678.9", Decimal("12345678.90")),
    (Decimals(10, 2), "123456789", None),
    (Decimals(10, 2), "0E-8", Decimal("0.00")),
    (Decimals(38, 0), "1" * 38, Decimal("1" * 38)),
    (Decimals(38, 0), "1" * 38 + ".4", None),  # 39 digits: no rounding into a fit
    (PG_NUMERIC, "1e30", Decimal("1e30")),
    (SINGLE, "3.4e38", 3.4e38),
    (SINGLE, "1e39", None),
    (SINGLE, "1e-38", None),  # below the smallest normal number
    (SINGLE, "-0.0", -0.0),
    (DOUBLE, "1e308", 1e308),
    (DOUBLE, "1e309", None),
    (DOUBLE, "1.7976931348623157000000000000000001e308", None),  # compared exactly
    (DOUBLE, "1e-320", None),
    (DOUBLE, "nan", None),
    (PG_MONEY, "$12.50", Decimal("12.50")),
    (PG_MONEY, "-$1,234.50", Decimal("-1234.50")),
    (PG_MONEY, "$12", Decimal("12.00")),
    (PG_MONEY, "12.5", Decimal("12.50")),
    (PG_MONEY, "$1,23", None),
    (PG_MONEY, "12.505", None),
    (PG_MONEY, "1e30", None),
    (PG_MONEY, "92233720368547758.08", None),
    (TSQL_MONEY, "922337203685477.5807", Decimal("922337203685477.5807")),
    (TSQL_MONEY, "922337203685477.5808", None),
    (TSQL_MONEY, "$12.50", None),
    (SMALLMONEY, "-214748.3648", Decimal("-214748.3648")),
    (SMALLMONEY, "214748.3648", None),
]


@pytest.mark.parametrize(("domain", "raw", "expected"), CHECKS)
def test_check_keeps_only_values_the_type_holds(domain: Domain, raw: str, expected: object) -> None:
    found = domain.check(raw)
    assert found == expected
    assert type(found) is type(expected)
    if isinstance(expected, Decimal):
        assert str(found) == str(expected)  # written with the column's scale


@pytest.mark.parametrize(
    ("dialect", "column_type", "domain"),
    [
        ("duckdb", "UBIGINT", U64),
        ("duckdb", "HUGEINT", Integers(-(1 << 127), 1 << 127)),
        ("postgres", "BIGINT", INT64),
        ("sqlite", "INTEGER", INT64),
        ("sqlite", "NUMERIC(10, 2)", DOUBLE),
        ("sqlite", "DATE", Texts()),
        ("postgres", "VARCHAR(20)", Texts(no_nul=True)),
        ("tsql", "NVARCHAR(10)", Texts()),
        ("postgres", "NUMERIC", PG_NUMERIC),
        ("postgres", "NUMERIC(10, 2)", Decimals(10, 2)),
        ("tsql", "DECIMAL(10)", Decimals(10, 0)),
        ("mysql", "DECIMAL", Decimals(10, 0)),
        ("postgres", "REAL", SINGLE),
        ("postgres", "DOUBLE PRECISION", DOUBLE),
        ("tsql", "FLOAT", DOUBLE),
        ("tsql", "REAL", SINGLE),
        ("mysql", "FLOAT", SINGLE),
        ("mysql", "FLOAT(24)", SINGLE),
        ("mysql", "FLOAT(25)", DOUBLE),
        ("mysql", "FLOAT(30)", DOUBLE),
        ("postgres", "DATE", Dates()),
        ("duckdb", "TIMESTAMP", NAIVE),
        ("tsql", "DATETIME2", NAIVE),
        ("mysql", "DATETIME", NAIVE),
        ("postgres", "TIMESTAMP WITH TIME ZONE", AWARE),
        ("tsql", "DATETIMEOFFSET", AWARE),
        ("tsql", "UNIQUEIDENTIFIER", Uuids()),
        ("duckdb", "BOOLEAN", Booleans()),
        ("postgres", "TIME", Nothing()),
        ("postgres", "JSON", Nothing()),
        ("tsql", "SMALLDATETIME", Nothing()),
        ("duckdb", "TIMESTAMP_NS", Nothing()),
    ],
)
def test_each_type_gets_its_check(dialect: str, column_type: str, domain: Domain) -> None:
    assert bind_domain(column_type, dialect) == domain


@pytest.mark.parametrize(
    ("dialect", "column_type", "raw", "expected"),
    [
        ("postgres", "MONEY", "-$1,234.50", Decimal("-1234.50")),
        ("tsql", "MONEY", "$12.50", None),
        ("tsql", "SMALLMONEY", "214748.3647", Decimal("214748.3647")),
        ("tsql", "SMALLMONEY", "214748.3648", None),
    ],
)
def test_money_type_gets_its_dialect_check(
    dialect: str, column_type: str, raw: str, expected: Decimal | None
) -> None:
    assert bind_domain(column_type, dialect).check(raw) == expected


def test_money_checks_differ_by_dialect() -> None:
    assert isinstance(PG_MONEY, Money)
    assert PG_MONEY.dollars
    assert isinstance(TSQL_MONEY, Money)
    assert not TSQL_MONEY.dollars
