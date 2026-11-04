"""`diff` reads the rules on rows and the query rate: a rule that hides less widens."""

from pathlib import Path

import pytest

from incognito_sql.cli import main

BASE = """dsn_env: SHOP_DSN
dialect: sqlite
columns:
  customers: {id: open, full_name: identifier, city: quasi, status: open}
entities: []
"""
CLOSED = "status = 'closed'"


def _rules(*rules: str) -> str:
    return BASE + "row_rules:\n" + "".join(f"  - {r}\n" for r in rules) if rules else BASE


def _rule(hide: str, where: str = CLOSED) -> str:
    return f'{{table: customers, hide: {hide}, where: "{where}"}}'


def _diff(
    tmp_path: Path, old: str, new: str, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    (tmp_path / "old.yaml").write_text(old, "utf-8")
    (tmp_path / "new.yaml").write_text(new, "utf-8")
    code = main(["diff", str(tmp_path / "old.yaml"), str(tmp_path / "new.yaml"), "--ci"])
    return code, capsys.readouterr().out


@pytest.mark.parametrize(
    ("old", "new", "lines"),
    [
        (_rules(_rule("'*'")), _rules(), ["WIDENED row_rules.customers: rule gone"]),
        (_rules(), _rules(_rule("'*'")), ["NARROWED row_rules.customers: rule added"]),
        (
            _rules(_rule("'*'")),
            _rules(_rule("'*'", "status = 'gone'")),
            ["WIDENED row_rules.customers: rule gone", "NARROWED row_rules.customers: rule added"],
        ),
        (
            _rules(_rule("'*'")),
            _rules(_rule("[full_name]")),
            ["WIDENED row_rules.customers: hides less (*)"],
        ),
        (
            _rules(_rule("[full_name]")),
            _rules(_rule("'*'")),
            ["NARROWED row_rules.customers: hides more"],
        ),
        (
            _rules(_rule("[full_name, city]")),
            _rules(_rule("[full_name]")),
            ["WIDENED row_rules.customers: hides less (city)"],
        ),
        (
            _rules(_rule("[full_name]")),
            _rules(_rule("[full_name, city]")),
            ["NARROWED row_rules.customers: hides more"],
        ),
        (BASE, BASE + "limits: {query_rate: 1000}\n", ["WIDENED limits.query_rate: 600 -> 1000"]),
        (BASE, BASE + "limits: {query_rate: 100}\n", ["NARROWED limits.query_rate: 600 -> 100"]),
        (
            BASE,
            BASE + "limits: {query_window_s: 30}\n",
            ["WIDENED limits.query_window_s: 60 -> 30"],
        ),
    ],
)
def test_each_rule_and_rate_change_is_judged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], old: str, new: str, lines: list[str]
) -> None:
    code, out = _diff(tmp_path, old, new, capsys)
    assert code == (1 if any(line.startswith("WIDENED") for line in lines) else 0)
    for line in lines:
        assert any(row.startswith(line) for row in out.splitlines()), (line, out)


def test_a_condition_spaced_otherwise_is_the_same_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spaced = _rules(_rule("'*'", "status  =   'closed'"))
    code, out = _diff(tmp_path, _rules(_rule("'*'")), spaced, capsys)
    assert code == 0
    assert "row_rules" not in out


def test_spacing_inside_a_literal_is_another_condition(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = _rules(_rule("'*'", "city = 'Tel  Aviv'"))
    code, out = _diff(tmp_path, old, _rules(_rule("'*'", "city = 'Tel Aviv'")), capsys)
    assert code == 1
    assert "WIDENED row_rules.customers: rule gone or its condition changed" in out
