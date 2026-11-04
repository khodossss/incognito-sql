"""`diff --ci` exits 1 on every widening it compares, and only on a widening."""

from pathlib import Path

import pytest

from incognito_sql.cli import main

BASE = """dsn_env: SHOP_DSN
dialect: sqlite
protection: strict
token_ttl_s: 3600
columns:
  customers: {id: quasi, full_name: identifier, city: open}
entities: []
"""


def _ci(tmp_path: Path, new: str, old: str = BASE) -> int:
    (tmp_path / "old.yaml").write_text(old, "utf-8")
    (tmp_path / "new.yaml").write_text(new, "utf-8")
    return main(["diff", str(tmp_path / "old.yaml"), str(tmp_path / "new.yaml"), "--ci"])


@pytest.mark.parametrize(
    ("new", "where"),
    [
        (BASE + "web_enabled: false\n", "web_enabled"),
        (
            BASE.replace("entities: []", "entities: [{table: customers, pk: id}]").replace(
                "id: quasi", "id: open"
            ),
            "customers.id",
        ),
        (BASE.replace("token_ttl_s: 3600", "token_ttl_s: null"), "token_ttl_s"),
        (BASE + "limits: {max_rows: 5000}\n", "limits.max_rows"),
        (BASE + "limits: {literal_window_s: 600}\n", "limits.literal_window_s"),
        (
            BASE + "protections: {mine: {extends: strict, allow: [prefix]}}\n"
            "column_protection: {customers: {full_name: mine}}\n",
            "customers.full_name",
        ),
        (BASE.replace("protection: strict", "protection: permissive"), "protection"),
        (BASE.replace("protection: strict", "protection: balanced"), "protection"),
    ],
)
def test_each_widening_fails_ci(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], new: str, where: str
) -> None:
    code = _ci(tmp_path, new)
    out = capsys.readouterr().out
    assert code == 1
    assert f"WIDENED {where}:" in out


def test_web_enabled_widens_both_ways(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = _ci(tmp_path, BASE, old=BASE + "web_enabled: false\n")
    assert code == 1
    assert "WIDENED web_enabled: False -> True" in capsys.readouterr().out


def test_removing_a_narrower_column_profile_widens(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    permissive = BASE.replace("protection: strict", "protection: permissive")
    pinned = permissive + "column_protection: {customers: {full_name: strict}}\n"
    code = _ci(tmp_path, permissive, old=pinned)
    assert code == 1
    assert "WIDENED customers.full_name: operations added:" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("new", "line"),
    [
        (
            BASE.replace("protection: strict", "protection: mine")
            + "protections: {mine: {extends: strict, allow: [is_null]}}\n",
            "CHANGED customers.full_name: operations added: is_null",
        ),
        (
            BASE.replace("dsn_env: SHOP_DSN", "dsn_env: OTHER_DSN"),
            "CHANGED dsn_env: the declaration applies to another database",
        ),
        (
            BASE.replace("token_ttl_s: 3600", "token_ttl_s: 600"),
            "NARROWED token_ttl_s: 3600 -> 600",
        ),
    ],
)
def test_what_opens_nothing_passes_ci(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], new: str, line: str
) -> None:
    code = _ci(tmp_path, new)
    assert code == 0
    assert line in capsys.readouterr().out.splitlines()


def test_a_removed_verified_column_narrows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _ci(tmp_path, BASE, old=BASE + "verified_open: {customers: [city]}\n")
    assert code == 0
    assert "NARROWED customers.city: verified_open removed" in capsys.readouterr().out


def test_an_unreadable_file_is_named_by_its_error_not_its_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "old.yaml").write_text(BASE, "utf-8")
    missing = tmp_path / "ghp_NotARealToken_123.yaml"
    assert main(["diff", str(tmp_path / "old.yaml"), str(missing)]) == 2
    err = capsys.readouterr().err
    assert "cannot read the new declaration: FileNotFoundError" in err
    assert "ghp_NotARealToken" not in err


@pytest.mark.parametrize("budget", ["literal_budget", "probe_budget"])
@pytest.mark.parametrize(
    "step",
    [
        (0, 5, "WIDENED"),
        (5, 0, "NARROWED"),
        (5, "unlimited", "WIDENED"),
        (0, "unlimited", "WIDENED"),
        ("unlimited", 5, "NARROWED"),
    ],
)
def test_a_budget_turned_on_or_lifted_widens_and_back_narrows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], budget: str, step: tuple[object, ...]
) -> None:
    before, after, kind = step

    def limited(n: object) -> str:
        return BASE + f"limits: {{{budget}: {n}}}\n"

    code = _ci(tmp_path, limited(after), old=limited(before))
    assert code == (kind == "WIDENED")
    assert f"{kind} limits.{budget}: {before} -> {after}" in capsys.readouterr().out


def test_a_verified_relation_added_widens_and_removed_narrows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    verified = BASE + "verified_relations: [customers]\n"
    assert _ci(tmp_path, verified) == 1
    assert "WIDENED customers: verified_relations: read with no rule on rows" in (
        capsys.readouterr().out
    )
    assert _ci(tmp_path, BASE, old=verified) == 0
    assert "NARROWED customers: verified_relations removed" in capsys.readouterr().out
