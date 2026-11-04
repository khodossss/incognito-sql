"""Computed numbers on every DBMS: an average is shown, an identifier-sized number masked."""

import re
from decimal import Decimal

import pytest

from incognito_sql.core.output.mask import MASK
from incognito_sql.core.pipeline import Gateway

from .conftest import Field

pytestmark = pytest.mark.integration
MASK_LINK = re.compile(r"http://127\.0\.0\.1:\d+/m/tk_[a-z2-7]{16}")


def _cells(gateway: Gateway, sql: str) -> list[object]:
    out = gateway.query(sql, "c1")
    rows = out.get("rows")
    assert isinstance(rows, list), out
    [row] = rows
    return list(row)


def test_average_of_a_decimal_column_is_shown(field: Field, gateway: Gateway) -> None:
    [avg, total] = _cells(gateway, field.sql("SELECT AVG(amount), SUM(amount) FROM orders"))
    assert avg != MASK
    assert abs(Decimal(str(avg)) - Decimal("118.3333333")) < Decimal("0.001")
    assert Decimal(str(total)) == Decimal(355)


def test_average_of_integers_is_shown(field: Field, gateway: Gateway) -> None:
    [avg] = _cells(gateway, field.sql("SELECT AVG(person_id) FROM orders"))
    assert avg != MASK
    integral = field.backend.dialect == "tsql"  # SQL Server averages integers as integers
    expected = Decimal(2) if integral else Decimal("2.3333")
    assert abs(Decimal(str(avg)) - expected) < Decimal("0.001")


def test_identifier_sized_computed_number_is_masked(field: Field, gateway: Gateway) -> None:
    [big] = _cells(gateway, field.sql("SELECT SUM(amount) * 10000000000 FROM orders"))
    assert MASK_LINK.fullmatch(str(big)), big  # web mode: a link only a human can open
