"""Budgets of 0 and unlimited end to end: refused at once, or counted nowhere."""

from datetime import UTC, datetime

from incognito_sql.core.config.report import protection_warnings

from .conftest import TOKEN, GatewayFactory


def test_literals_off_leave_tokens_and_open_columns(make_gateway: GatewayFactory) -> None:
    gw = make_gateway("limits: {literal_budget: 0}\n")
    out = gw.query("SELECT id, full_name FROM people WHERE city = 'Eilat'", "c1")
    found = TOKEN.search(str(out["rows"]))
    assert found, out
    assert gw.query("SELECT id FROM people WHERE full_name = 'Ivan Petrov'", "c1") == {
        "error": "literals_off",
        "sqlstate": None,
    }
    by_token = f"SELECT id FROM people WHERE full_name = '{found.group(0)}'"  # noqa: S608
    assert gw.query(by_token, "c1")["rows"] == [[3]]
    assert not gw._budget.alarm_active(datetime.now(UTC))  # noqa: SLF001


def test_probes_off_refuse_a_probe_without_an_alarm(make_gateway: GatewayFactory) -> None:
    gw = make_gateway("limits: {probe_budget: 0}\n")
    assert gw.query("SELECT id FROM people ORDER BY full_name", "c1")["error"] == "probes_off"
    assert "rows" in gw.query("SELECT id FROM people ORDER BY id", "c1")
    assert not gw._budget.alarm_active(datetime.now(UTC))  # noqa: SLF001


def test_unlimited_budgets_count_nothing_and_say_so(make_gateway: GatewayFactory) -> None:
    gw = make_gateway("limits: {literal_budget: unlimited, probe_budget: unlimited}\n")
    for i in range(30):
        sql = f"SELECT id FROM people WHERE full_name = 'Zqname {i}' OR full_name > 'M{i}'"  # noqa: S608
        assert "rows" in gw.query(sql, f"c{i % 2}")
    assert not gw._budget.alarm_active(datetime.now(UTC))  # noqa: SLF001
    said = " ".join(protection_warnings(gw._decl))  # noqa: SLF001
    assert "literal_budget is unlimited" in said
    assert "probe_budget is unlimited" in said
