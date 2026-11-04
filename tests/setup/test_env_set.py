"""`env` keeps a variable that is no secret; `set` changes one top-level setting."""

import argparse
import os
from pathlib import Path

import pytest

from incognito_sql.cli import main
from incognito_sql.core.config import load_declaration
from incognito_sql.demo import run_demo
from incognito_sql.envfile import load_env_file
from incognito_sql.setup.env import add_env_parser, run_env
from incognito_sql.setup.setkey import updated


def _env(*argv: str, user: bool = True) -> tuple[int, dict[str, str]]:
    parser = argparse.ArgumentParser()
    add_env_parser(parser.add_subparsers(dest="command"))
    kept = dict[str, str]()
    code = run_env(parser.parse_args(["env", *argv]), kept.__setitem__ if user else None)
    return code, kept


def test_a_database_file_becomes_its_dsn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOP_DSN", "")  # records its absence, which the teardown restores
    monkeypatch.delenv("SHOP_DSN")
    db = tmp_path / "shop.db"
    code, kept = _env("SHOP_DSN", "--file", str(db), "--dialect", "duckdb")
    assert code == 0
    assert kept == {"SHOP_DSN": f"duckdb:///{db.resolve().as_posix()}"}
    assert os.environ["SHOP_DSN"] == kept["SHOP_DSN"]


def test_an_env_file_holds_it_where_there_is_no_user_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHOP_DSN", "")  # records its absence, which the teardown restores
    monkeypatch.delenv("SHOP_DSN")
    env = tmp_path / "demo.env"
    assert _env("SHOP_DSN", "x", user=False)[0] == 2
    assert _env("SHOP_DSN", "x", "--env-file", str(env), user=False)[0] == 0
    read: dict[str, str] = {}
    load_env_file(env, read)
    assert read == {"SHOP_DSN": "x"}


@pytest.mark.parametrize(
    "argv", [("shop_dsn", "x"), ("SHOP_DSN",), ("SHOP_DSN", "x", "--file", "f")]
)
def test_a_bad_call_keeps_nothing(argv: tuple[str, ...]) -> None:
    assert _env(*argv) == (2, {})


def test_set_replaces_a_line_and_keeps_the_rest() -> None:
    text = "# keep me\ndsn_env: X\nprotection: strict  # was\ncolumns: {}\n"
    assert updated(text, "protection", "balanced") == (
        "# keep me\ndsn_env: X\nprotection: balanced\ncolumns: {}\n"
    )
    assert updated("dsn_env: X", "web_port", "8767") == "dsn_env: X\nweb_port: 8767\n"


def test_set_leaves_a_file_that_would_not_load(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_demo(tmp_path) == 0
    config = tmp_path / "shop.yaml"
    before = config.read_text("utf-8")
    assert main(["set", str(config), "protection", "balanced"]) == 0
    assert load_declaration(config).protection == "balanced"
    assert main(["set", str(config), "protection", "Zq7nosuchprofile"]) == 1
    assert load_declaration(config).protection == "balanced"
    assert main(["set", str(config), "web_port", "1\nprotection: permissive"]) == 1
    assert "Zq7" not in capsys.readouterr().err
    assert config.read_text("utf-8") != before
