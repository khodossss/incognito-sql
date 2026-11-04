"""The query pipeline end to end on SQLite: links, follow-up by token, labels, refusals."""

import json
import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

import pytest

from incognito_sql.core import pipeline
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.pipeline import Gateway
from incognito_sql.wiring import store_path

from .conftest import TOKEN, GatewayFactory, World

CONN = "c1"


def _rows(out: dict[str, object]) -> list[list[object]]:
    rows = out["rows"]
    assert isinstance(rows, list), out
    return rows


def _token(cell: object) -> str:
    assert isinstance(cell, str)
    found = TOKEN.search(cell)
    assert found, cell
    return found.group(0)


def test_literal_question_returns_a_link(gateway: Gateway) -> None:
    out = gateway.query("SELECT id, full_name FROM people WHERE full_name = 'Ivan Petrov'", CONN)
    [[pk, link]] = _rows(out)
    assert pk == 1
    assert isinstance(link, str)
    assert link.startswith("http://127.0.0.1:8765/v/tk_")
    assert out["hidden_columns"] == 0
    assert out["truncated"] is False


def test_follow_up_by_token_returns_the_same_rows(gateway: Gateway) -> None:
    first = gateway.query("SELECT id, full_name FROM people WHERE full_name = 'Ivan Petrov'", CONN)
    token = _token(_rows(first)[0][1])
    follow_up = "SELECT id, full_name FROM people WHERE full_name = '{}'"
    again = gateway.query(follow_up.format(token), CONN)
    assert _rows(again) == _rows(first)
    in_orders = "SELECT id FROM orders WHERE customer_name IN ('{}')"
    orders = gateway.query(in_orders.format(token), CONN)
    assert _rows(orders) == [[10]]


def test_spelling_variants_share_one_link(gateway: Gateway) -> None:
    out = gateway.query("SELECT customer_name FROM orders WHERE person_id = 3", CONN)
    links = {cell for [cell] in _rows(out)}
    assert len(links) == 1


def test_star_counts_hidden_columns(gateway: Gateway) -> None:
    out = gateway.query("SELECT * FROM people WHERE id = 2", CONN)
    assert out["columns"] == ["id", "full_name", "city"]
    assert out["hidden_columns"] == 2


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT secret_note FROM people", Reason.HIDDEN_COLUMN),
        ("SELECT bio FROM people", Reason.HIDDEN_COLUMN),
        ("SELECT upper(full_name) FROM people", Reason.PII_OPERATION),
        ("DELETE FROM people", Reason.NODE_NOT_ALLOWED),
        ("SELECT nope FROM people", Reason.UNKNOWN_COLUMN),
        ("SELECT (", Reason.PARSE_ERROR),
    ],
)
def test_rejection_shape(gateway: Gateway, sql: str, reason: Reason) -> None:
    assert gateway.query(sql, CONN) == {"error": reason.value, "sqlstate": None}


def test_db_error_carries_sqlstate_and_detail(
    gateway: Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: object) -> None:
        raise Rejection(Reason.DB_ERROR, sqlstate="42P01", detail="relation missing")

    monkeypatch.setattr(pipeline, "execute", fail)
    out = gateway.query("SELECT id FROM people", CONN)
    assert out == {"error": "db_error", "sqlstate": "42P01", "detail": "relation missing"}


def test_internal_error_keeps_the_exception_text_out(
    gateway: Gateway, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_: object, **__: object) -> None:
        msg = "Zqcanary Person"
        raise RuntimeError(msg)

    monkeypatch.setattr(pipeline, "shape", boom)
    with caplog.at_level(logging.DEBUG):
        out = gateway.query("SELECT full_name FROM people", CONN)
    assert out == {"error": Reason.INTERNAL_ERROR.value}
    assert "RuntimeError" in caplog.text
    assert "zqcanary" not in caplog.text.casefold()


def test_literal_budget_is_spent_per_connection(make_gateway: GatewayFactory) -> None:
    gw = make_gateway("limits: {literal_budget: 1}\n")
    sql = "SELECT id FROM people WHERE full_name = '{}'"
    assert "rows" in gw.query(sql.format("Ivan Petrov"), CONN)
    assert gw.query(sql.format("Anna Ivanova"), CONN) == {
        "error": "literal_budget",
        "sqlstate": None,
    }


def test_a_query_refused_after_the_budget_has_spent_its_literals(
    make_gateway: GatewayFactory,
) -> None:
    gw = make_gateway("limits: {literal_budget: 1}\n")
    overflow = (
        "SELECT id FROM people WHERE full_name = 'Zqno A' AND abs(-9223372036854775807 - 1) > 0"
    )
    assert gw.query(overflow, CONN)["error"] == "db_error"
    honest = "SELECT id FROM people WHERE full_name = 'Ivan Petrov'"
    assert gw.query(honest, CONN)["error"] == "literal_budget"


def _tokens(world: World) -> int:
    with closing(sqlite3.connect(store_path(world.config))) as con:
        return int(con.execute("SELECT COUNT(*) FROM token").fetchone()[0])


def test_a_query_refused_before_the_database_spends_nothing(
    make_gateway: GatewayFactory, world: World
) -> None:
    gw = make_gateway("limits: {literal_budget: 2, probe_budget: 1}\n")
    before = _tokens(world)
    late = (
        "SELECT id FROM people WHERE (full_name = 'Zqno A' OR full_name = 'tk_aaaaaaaaaaaaaaaa')"
        " AND full_name > 'M'"
    )
    assert gw.query(late, CONN)["error"] == "invalid_token"  # the binder, past the policy
    assert _tokens(world) == before  # no token was issued for the refused literal
    line = json.loads(world.audit.read_text(encoding="utf-8").splitlines()[-1])
    assert "Zqno" not in line["sql_tokenized"]
    assert not TOKEN.search(line["sql_tokenized"].replace("tk_aaaaaaaaaaaaaaaa", ""))
    probe = "SELECT id FROM people WHERE full_name = 'Anna Ivanova' AND full_name > 'M'"
    assert "rows" in gw.query(probe, CONN)  # both budgets are as before the refused query


def test_audit_records_every_outcome(
    gateway: Gateway, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    gateway.query("SELECT id FROM people p WHERE p.full_name = 'Zqcanary Person'", CONN, now)
    gateway.query("SELECT secret_note FROM people", CONN, now)
    monkeypatch.setattr(pipeline, "shape", lambda *_, **__: 1 / 0)
    gateway.query("SELECT o.id FROM orders o JOIN people p ON p.id = o.person_id", CONN, now)
    lines = [json.loads(x) for x in world.audit.read_text(encoding="utf-8").splitlines()]
    assert [(x["outcome"], x["reason"]) for x in lines] == [
        ("ok", None),
        ("rejected", "hidden_column"),
        ("error", "internal_error"),
    ]
    assert lines[0]["tables"] == ["people"]
    assert lines[0]["row_count"] == 1
    assert _token(lines[0]["sql_tokenized"])
    assert lines[1]["tables"] == ["people"]  # resolved before the policy refused it
    assert lines[1]["sql_tokenized"] is None
    assert lines[2]["tables"] == ["orders", "people"]
    # base columns read in any place, by name only; a refused query's too
    assert lines[0]["columns"] == ["people.full_name", "people.id"]
    assert lines[1]["columns"] == ["people.secret_note"]
    assert lines[2]["columns"] == ["orders.id", "orders.person_id", "people.id"]


def test_audit_names_columns_behind_stars_and_subqueries(gateway: Gateway, world: World) -> None:
    gateway.query("SELECT * FROM orders", CONN)
    gateway.query("SELECT x FROM (SELECT full_name AS x FROM people) s WHERE x <> 'a'", CONN)
    lines = [json.loads(x) for x in world.audit.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["columns"] == [
        "orders.amount",
        "orders.customer_name",
        "orders.id",
        "orders.person_id",
    ]
    assert lines[1]["columns"] == ["people.full_name"]
    assert "zqcanary" not in world.audit.read_text(encoding="utf-8").casefold()


def test_audit_names_star_columns_of_a_query_the_database_failed(
    gateway: Gateway, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(*_: object) -> None:
        raise Rejection(Reason.DB_ERROR)

    monkeypatch.setattr(pipeline, "execute", failing)
    assert gateway.query("SELECT * FROM orders", CONN)["error"] == "db_error"
    line = json.loads(world.audit.read_text(encoding="utf-8").splitlines()[-1])
    assert "orders.customer_name" in line["columns"]


def test_unaudited_answer_is_not_given(gateway: Gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(**_: object) -> None:
        raise OSError

    real = gateway._audit  # noqa: SLF001 -- its anchor is closed with the gateway
    fake = type("A", (), {"record": staticmethod(broken), "close": staticmethod(real.close)})
    monkeypatch.setattr(gateway, "_audit", fake())
    assert gateway.query("SELECT id FROM people", CONN) == {"error": "internal_error"}


def test_the_query_rate_counts_refused_queries_and_refuses_before_parsing(
    make_gateway: GatewayFactory, world: World
) -> None:
    gw = make_gateway("limits: {query_rate: 2, query_window_s: 60}\n")
    assert gw.query("DELETE FROM people", CONN)["error"] == "node_not_allowed"  # counted too
    assert "rows" in gw.query("SELECT id FROM people", CONN)
    assert gw.query("SELECT id FROM people", CONN) == {"error": "rate_limit", "sqlstate": None}
    last = json.loads(world.audit.read_text(encoding="utf-8").splitlines()[-1])
    assert (last["reason"], last["tables"], last["sql_tokenized"]) == ("rate_limit", [], None)


def test_ask_gives_what_the_query_spent_and_the_audit_its_probes(
    make_gateway: GatewayFactory, world: World
) -> None:
    gw = make_gateway("limits: {literal_budget: 5, probe_budget: 5}\n")
    probe = "SELECT id FROM people WHERE full_name = 'Anna Ivanova' AND full_name > 'M'"
    answer, spend = gw.ask(probe, CONN)
    assert "rows" in answer
    assert (spend.literals, spend.probes) == (2, 1)
    _, again = gw.ask(probe, CONN)
    assert (again.literals, again.probes) == (0, 1)  # the literals are already in the window
    refused, nothing = gw.ask("SELECT secret_note FROM people", CONN)
    assert refused["error"] == "hidden_column"
    assert (nothing.literals, nothing.probes) == (0, 0)
    lines = [json.loads(x) for x in world.audit.read_text(encoding="utf-8").splitlines()]
    assert [x["probes"] for x in lines] == [1, 1, 0]


def test_unlimited_budgets_count_nothing(make_gateway: GatewayFactory) -> None:
    gw = make_gateway("limits: {literal_budget: unlimited, probe_budget: unlimited}\n")
    answer, spend = gw.ask("SELECT id FROM people WHERE full_name > 'M'", CONN)
    assert "rows" in answer
    assert (spend.literals, spend.probes) == (0, 0)
