"""A literal left of IN against an identifier: matched by its forms, like `=`."""

import pytest

from incognito_sql.core.pipeline import Gateway

from .conftest import TOKEN

CONN = "c1"


def _ids(gateway: Gateway, sql: str) -> list[object]:
    out = gateway.query(sql, CONN)
    rows = out.get("rows")
    assert isinstance(rows, list), out
    return sorted(row[0] for row in rows)


@pytest.mark.parametrize("written", ["'Ivan Petrov'", "('Ivan Petrov')", "'ivan petrov '"])
def test_a_literal_left_of_in_matches_its_forms(gateway: Gateway, written: str) -> None:
    gateway.query("SELECT full_name FROM people", CONN)  # the database's spelling is known
    assert _ids(gateway, f"SELECT id FROM people WHERE {written} IN (full_name)") == [1]  # noqa: S608


def test_a_token_left_of_in_matches(gateway: Gateway) -> None:
    out = gateway.query("SELECT full_name FROM people WHERE id = 1", CONN)
    token = TOKEN.search(str(out))
    assert token is not None
    sql = f"SELECT id FROM people WHERE '{token.group(0)}' IN (full_name)"  # noqa: S608
    assert _ids(gateway, sql) == [1]


@pytest.mark.parametrize(
    ("items", "reason"),
    [
        ("p.full_name, o.customer_name", "pii_operation"),
        ("p.full_name, p.city", "pii_join_with_open"),
    ],
)
def test_a_literal_left_of_a_longer_list_is_refused(
    gateway: Gateway, items: str, reason: str
) -> None:
    sql = (
        "SELECT p.id FROM people p JOIN orders o ON o.person_id = p.id "  # noqa: S608
        f"WHERE 'Ivan Petrov' IN ({items})"
    )
    assert gateway.query(sql, CONN)["error"] == reason


def test_a_literal_left_of_a_subquery_is_refused(gateway: Gateway) -> None:
    sql = "SELECT id FROM people WHERE 'Ivan Petrov' IN (SELECT full_name FROM people)"
    assert gateway.query(sql, CONN)["error"] == "pii_operation"
