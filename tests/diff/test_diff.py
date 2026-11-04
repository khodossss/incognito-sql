"""`diff`: what a new declaration shows the model more or less, and `--ci` stops a widening."""

from pathlib import Path

import pytest

from incognito_sql.cli import main

BASE = """dsn_env: SHOP_DSN
dialect: sqlite
protection: strict
columns:
  customers: {id: open, full_name: identifier, email: identifier, city: quasi, notes: free_text}
entities:
  - {table: customers, pk: id}
"""


def _files(tmp_path: Path, new: str, old: str = BASE) -> tuple[str, str]:
    (tmp_path / "old.yaml").write_text(old, "utf-8")
    (tmp_path / "new.yaml").write_text(new, "utf-8")
    return str(tmp_path / "old.yaml"), str(tmp_path / "new.yaml")


def _report(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().out.splitlines()


def test_the_same_declaration_has_no_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["diff", *_files(tmp_path, BASE), "--ci"]) == 0
    assert _report(capsys) == ["0 changes, 0 widened"]


def test_classes_are_judged_by_what_the_model_sees(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    new = (
        BASE.replace("email: identifier", "email: open")
        .replace("full_name: identifier", "full_name: secret")
        .replace("city: quasi", "city: open")
        .replace(", notes: free_text", ", phone: identifier")
    )
    assert main(["diff", *_files(tmp_path, new)]) == 0  # without --ci, a report only
    assert _report(capsys) == [
        "WIDENED customers.email: identifier -> open",
        "WIDENED customers.phone: hidden -> identifier",
        "NARROWED customers.full_name: identifier -> closed_hidden",
        "CHANGED customers.city: open_quasi -> open",
        "CHANGED customers.notes: closed -> hidden",
        "5 changes, 2 widened",
    ]


def test_a_wider_profile_and_budget_widen_and_ci_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    new = (
        BASE.replace("protection: strict", "protection: permissive")
        + "limits: {literal_budget: 40}\nverified_open: {customers: [city]}\n"
    )
    assert main(["diff", *_files(tmp_path, new), "--ci"]) == 1
    report = _report(capsys)
    assert "WIDENED customers.city: verified_open: its mask is lifted" in report
    assert "WIDENED limits.literal_budget: 20 -> 40" in report
    assert any(line.startswith("WIDENED customers.email: operations added:") for line in report)
    assert any(line.startswith("WIDENED protection: query forms added:") for line in report)


def test_a_narrower_declaration_passes_ci(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = BASE.replace("protection: strict", "protection: permissive")
    new = BASE + "column_protection: {customers: {email: strict}}\n"
    new += "limits: {literal_window_s: 7200}\n"
    assert main(["diff", *_files(tmp_path, new, old), "--ci"]) == 0
    report = _report(capsys)
    assert all(not line.startswith("WIDENED") for line in report)
    assert "NARROWED limits.literal_window_s: 3600 -> 7200" in report
    assert any(line.startswith("NARROWED customers.email: operations removed:") for line in report)


def test_an_unreadable_declaration_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old, _ = _files(tmp_path, BASE)
    assert main(["diff", old, str(tmp_path / "missing.yaml")]) == 2
    assert "cannot read" in capsys.readouterr().err
