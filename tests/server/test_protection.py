"""Protection profiles end to end: the gateway, the description, the operator's warnings."""

import io
from pathlib import Path

import pytest

from incognito_sql import cli
from incognito_sql.check.run import protection_report

from .conftest import GatewayFactory, World

NULL_TEST = "SELECT id FROM people WHERE full_name IS NOT NULL ORDER BY id"


def test_default_profile_answers_a_null_test(make_gateway: GatewayFactory) -> None:
    answer = make_gateway("").query(NULL_TEST, "c1")
    assert "error" not in answer
    assert answer["rows"] == [[1], [2], [3]]


def test_strict_refuses_a_null_test(make_gateway: GatewayFactory) -> None:
    answer = make_gateway("protection: strict\n").query(NULL_TEST, "c1")
    assert answer["error"] == "pii_operation"


def test_column_profile_holds_only_its_column(make_gateway: GatewayFactory) -> None:
    gw = make_gateway("column_protection: {orders: {customer_name: strict}}\n")
    assert "error" not in gw.query(NULL_TEST, "c1")
    held = gw.query("SELECT id FROM orders WHERE customer_name IS NULL", "c1")
    assert held["error"] == "pii_operation"
    view = gw.describe()
    assert "is_null" in view["identifier_operations"]  # type: ignore[operator]
    orders = view["tables"]["orders"]  # type: ignore[index]
    assert "is_null" not in orders["identifier_operations"]["customer_name"]


def test_serve_warns_the_operator_on_stderr(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_run_stdio", lambda _server: None)
    assert cli.main(["serve", "--config", str(world.config)]) == 0
    captured = capsys.readouterr()
    assert "warning: protection permissive" in captured.err
    assert "follows permissive" in captured.err
    assert captured.out == ""  # stdout belongs to MCP


def test_balanced_serve_says_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world.write_config("protection: balanced\n")
    monkeypatch.setattr(cli, "_run_stdio", lambda _server: None)
    assert cli.main(["serve", "--config", str(world.config)]) == 0
    assert "warning" not in capsys.readouterr().err


def test_check_prints_what_the_profiles_open(world: World, tmp_path: Path) -> None:
    out = io.StringIO()
    protection_report(world.config, out)
    text = out.getvalue()
    assert "protection: permissive" in text
    assert "L3 existence" in text
    assert "warning:" in text
    silent = io.StringIO()
    protection_report(tmp_path / "missing.yaml", silent)
    protection_report(None, silent)
    assert silent.getvalue() == ""


def test_a_probe_literal_is_not_audited_and_spends_the_budget(
    make_gateway: GatewayFactory, world: World
) -> None:
    gw = make_gateway("limits: {literal_budget: 2}\n")
    sql = "SELECT id FROM people WHERE full_name > '{}' ORDER BY id"
    assert "error" not in gw.query(sql.format("Zqprobe One"), "c1")
    assert "error" not in gw.query(sql.format("Zqprobe Two"), "c1")
    assert gw.query(sql.format("Zqprobe Three"), "c1")["error"] == "literal_budget"
    audit = world.audit.read_text(encoding="utf-8")
    assert "zqprobe" not in audit.casefold()
    assert "> '?'" in audit


def test_an_aggregate_compared_with_a_literal_answers(make_gateway: GatewayFactory) -> None:
    gw = make_gateway("")
    found = gw.query("SELECT count(*) FROM people HAVING max(full_name) = 'Zqcanary Person'", "c1")
    assert found["rows"] == [[3]]
    missed = gw.query("SELECT count(*) FROM people HAVING max(full_name) = 'Zqno Such'", "c1")
    assert missed["rows"] == []


def test_each_spelling_of_a_probe_spends_the_budget(make_gateway: GatewayFactory) -> None:
    gw = make_gateway("limits: {literal_budget: 2}\n")
    sql = "SELECT id FROM people WHERE full_name > '{}' ORDER BY id"
    assert "error" not in gw.query(sql.format("M"), "c1")
    assert "error" not in gw.query(sql.format("m"), "c1")
    assert gw.query(sql.format(" M "), "c1")["error"] == "literal_budget"


def test_a_literal_left_of_a_longer_list_spends_nothing(
    make_gateway: GatewayFactory, world: World
) -> None:
    gw = make_gateway("limits: {literal_budget: 1}\n")
    refused = "SELECT id FROM people WHERE 'Zqno One' IN (full_name, full_name)"
    assert gw.query(refused, "c1")["error"] == "pii_operation"
    honest = "SELECT id FROM people WHERE full_name = 'Ivan Petrov'"
    assert gw.query(honest, "c1")["rows"] == [[1]]
    assert "zqno" not in world.audit.read_text(encoding="utf-8").casefold()


def test_a_range_offset_over_an_identifier_is_refused(make_gateway: GatewayFactory) -> None:
    gw = make_gateway("")
    window = "SELECT id, count(*) OVER (ORDER BY full_name {}) FROM people ORDER BY id"
    refused = gw.query(window.format("RANGE BETWEEN 1 PRECEDING AND CURRENT ROW"), "c1")
    assert refused["error"] == "pii_operation"
    assert "error" not in gw.query(window.format("ROWS BETWEEN 1 PRECEDING AND CURRENT ROW"), "c1")
