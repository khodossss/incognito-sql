"""The end-to-end pipeline on every DBMS: links, follow-up by token, refusals, binds."""

import re

import pytest

from incognito_sql.core.errors import Reason
from incognito_sql.core.pipeline import Gateway

from .conftest import Field

pytestmark = pytest.mark.integration
CONN = "c1"
TOKEN = re.compile(r"tk_[a-z2-7]{16}")


def rows(out: dict[str, object]) -> list[list[object]]:
    """The rows of an answer, as lists; shuffled, as the gateway returns them."""
    found = out.get("rows")
    assert isinstance(found, list), out
    return [list(row) for row in found]


def token(cell: object) -> str:
    assert isinstance(cell, str), cell
    found = TOKEN.search(cell)
    assert found, cell
    return found.group(0)


def test_literal_question_returns_a_link(field: Field, gateway: Gateway) -> None:
    sql = field.sql("SELECT id, full_name FROM people WHERE full_name = 'Ivan Petrov'")
    out = gateway.query(sql, CONN)
    [[pk, link]] = rows(out)
    assert pk == 1
    assert isinstance(link, str)
    assert link.startswith("http://127.0.0.1:8765/v/tk_")
    assert out["hidden_columns"] == 0


def test_follow_up_by_token_returns_the_same_rows(field: Field, gateway: Gateway) -> None:
    sql = "SELECT id, full_name FROM people WHERE full_name = '{}'"
    first = gateway.query(field.sql(sql.format("Ivan Petrov")), CONN)
    tk = token(rows(first)[0][1])
    assert rows(gateway.query(field.sql(sql.format(tk)), CONN)) == rows(first)
    in_orders = "SELECT id FROM orders WHERE customer_name IN ('{}')"
    orders = gateway.query(field.sql(in_orders.format(tk)), CONN)
    assert rows(orders) == [[10]]


def test_spelling_variants_share_one_link(field: Field, gateway: Gateway) -> None:
    out = gateway.query(field.sql("SELECT customer_name FROM orders WHERE person_id = 3"), CONN)
    assert len({cell for [cell] in rows(out)}) == 1


def test_star_counts_hidden_columns(field: Field, gateway: Gateway) -> None:
    out = gateway.query(field.sql("SELECT * FROM people WHERE id = 2"), CONN)
    assert out["columns"] == ["id", "full_name", "city", "phone"]
    assert out["hidden_columns"] == 2


def test_numeric_identifier_binds_as_a_number(field: Field, gateway: Gateway) -> None:
    sql = "SELECT id, phone FROM people WHERE phone = {}"
    first = gateway.query(field.sql(sql.format("501234567")), CONN)
    [[pk, link]] = rows(first)
    assert pk == 1
    again = gateway.query(field.sql(sql.format(f"'{token(link)}'")), CONN)
    assert rows(again) == rows(first)


def test_open_columns_compare_with_bound_literals(field: Field, gateway: Gateway) -> None:
    sql = "SELECT id, amount FROM orders WHERE amount > 1.5 AND id <> 12 AND person_id IN (1, 3)"
    out = gateway.query(field.sql(sql), CONN)
    assert sorted([pk, float(str(amount))] for pk, amount in rows(out)) == [
        [10, 100.0],
        [11, 250.0],
    ]


def test_cut_rows_are_drawn_at_random(field: Field, gateway: Gateway) -> None:
    sql = "SELECT customer_name, amount FROM orders ORDER BY amount DESC LIMIT 2"
    out = gateway.query(field.sql(sql), CONN)
    assert sorted(float(str(a)) for _, a in rows(out)) == [100.0, 250.0]
    nested = "SELECT n.id FROM (SELECT id FROM orders ORDER BY id OFFSET 1) AS n"
    if field.backend.dialect in {"mysql", "sqlite"}:  # no OFFSET without LIMIT: refused first
        assert gateway.query(nested, CONN) == {"error": "node_not_allowed", "sqlstate": None}
    else:
        assert sorted(rows(gateway.query(field.sql(nested), CONN))) == [[11], [12]]
    scalar = "SELECT id, (SELECT MAX(amount) FROM orders) AS mx FROM people WHERE id = 1"
    assert len(rows(gateway.query(field.sql(scalar), CONN))) == 1
    distinct = "SELECT id, (SELECT DISTINCT person_id FROM orders WHERE id = 10) AS p FROM people"
    assert sorted(rows(gateway.query(field.sql(distinct), CONN))) == [[1, 1], [2, 1], [3, 1]]


def test_the_random_key_is_drawn_per_row(field: Field, gateway: Gateway) -> None:
    # A key fixed per query (SQL Server's RAND()) would always cut the same row.
    sql = field.sql("SELECT id FROM orders LIMIT 1")
    firsts = {rows(gateway.query(sql, CONN))[0][0] for _ in range(40)}
    assert len(firsts) > 1


def test_offset_with_a_limit_in_a_subquery(field: Field, gateway: Gateway) -> None:
    sql = "SELECT n.id FROM (SELECT id FROM orders ORDER BY id LIMIT 2 OFFSET 1) AS n"
    out = gateway.query(field.sql(sql), CONN)
    if field.backend.dialect == "tsql":  # OFFSET ... FETCH is not in the allowlist
        assert out == {"error": "node_not_allowed", "sqlstate": None}
    else:
        assert sorted(rows(out)) == [[11], [12]]


def test_grouping_keeps_one_bind_per_value(field: Field, gateway: Gateway) -> None:
    sql = "SELECT amount + 1 AS a, COUNT(*) AS n FROM orders GROUP BY amount + 1"
    out = gateway.query(field.sql(sql), CONN)
    assert sorted(float(str(a)) for a, _ in rows(out)) == [6.0, 101.0, 251.0]


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT secret_note FROM people", Reason.HIDDEN_COLUMN),
        ("SELECT bio FROM people", Reason.HIDDEN_COLUMN),
        ("SELECT upper(full_name) FROM people", Reason.PII_OPERATION),
        ("SELECT nope FROM people", Reason.UNKNOWN_COLUMN),
        ("SELECT login FROM staff", Reason.HIDDEN_COLUMN),
    ],
)
def test_rejection_shape(field: Field, gateway: Gateway, sql: str, reason: Reason) -> None:
    assert gateway.query(field.sql(sql), CONN) == {"error": reason.value, "sqlstate": None}


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("DELETE FROM people", Reason.NODE_NOT_ALLOWED),
        ("SELECT (", Reason.PARSE_ERROR),
        ("SELECT 1; SELECT 2", Reason.MULTIPLE_STATEMENTS),
    ],
)
def test_rejection_of_raw_text(gateway: Gateway, sql: str, reason: Reason) -> None:
    assert gateway.query(sql, CONN) == {"error": reason.value, "sqlstate": None}
