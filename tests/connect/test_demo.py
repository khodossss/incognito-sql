"""`demo`: an invented shop the server answers with tokens, written once per folder."""

import sqlite3
from pathlib import Path

import pytest

from incognito_sql.cli import main
from incognito_sql.core.config import load_declaration
from incognito_sql.demo import DSN_ENV
from incognito_sql.wiring import open_gateway


def test_the_demo_answers_with_tokens(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert DSN_ENV in out
    assert "incognito-sql connect claude-code --config" in out
    config, database = tmp_path / "shop.yaml", tmp_path / "shop.db"
    with sqlite3.connect(database) as con:
        assert con.execute("SELECT COUNT(*) FROM customers").fetchone() == (4,)
    con.close()
    decl = load_declaration(config)
    dsn = f"sqlite:///{database.as_posix()}"
    gateway = open_gateway(config, decl, dsn, bytes(range(32)))
    try:
        answer = gateway.query("SELECT full_name, city FROM customers WHERE id = 1", "demo")
    finally:
        gateway.close()
    rows = answer["rows"]
    assert isinstance(rows, list)
    assert "/v/tk_" in str(rows[0][0])
    assert "Quellbrandt" not in str(answer)


def test_a_used_folder_is_left_alone(tmp_path: Path) -> None:
    assert main(["demo", str(tmp_path)]) == 0
    before = (tmp_path / "shop.yaml").read_text("utf-8")
    assert main(["demo", str(tmp_path)]) == 1
    assert (tmp_path / "shop.yaml").read_text("utf-8") == before
