"""The model's outer ORDER BY decides the answer's order on every DBMS; ties stay random."""

import pytest

from incognito_sql.core.pipeline import Gateway

from .conftest import Field

pytestmark = pytest.mark.integration
SQL = "SELECT p.city, p.id AS pid, o.id AS oid FROM people AS p CROSS JOIN orders AS o"


def _rows(gateway: Gateway, sql: str) -> list[list[object]]:
    out = gateway.query(sql, "c1")
    rows = out.get("rows")
    assert isinstance(rows, list), out
    return rows


@pytest.mark.parametrize("desc", [False, True])
def test_rows_follow_the_outer_order_by(field: Field, gateway: Gateway, *, desc: bool) -> None:
    direction = " DESC" if desc else ""
    rows = _rows(gateway, field.sql(f"{SQL} ORDER BY p.city{direction}, o.id"))
    cities = ["Eilat"] * 3 + ["Haifa"] * 6
    assert [r[0] for r in rows] == (cities[::-1] if desc else cities)
    haifa = [int(str(r[2])) for r in rows if r[0] == "Haifa"]
    assert haifa == sorted(haifa)


def test_tied_rows_vary(field: Field, gateway: Gateway) -> None:
    sql = field.sql(f"{SQL} ORDER BY p.city")
    seen = {tuple((r[1], r[2]) for r in _rows(gateway, sql) if r[0] == "Haifa") for _ in range(30)}
    assert len(seen) > 1


def test_no_order_by_is_shuffled(field: Field, gateway: Gateway) -> None:
    seen = {tuple(map(tuple, _rows(gateway, field.sql(SQL)))) for _ in range(30)}
    assert len(seen) > 1
