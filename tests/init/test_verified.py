"""`init` on a file with verified columns: they are no longer contradictions."""

from pathlib import Path

import pytest

from incognito_sql.cli import main
from incognito_sql.core.config import Declaration
from incognito_sql.init.report import Samples, contradictions

from .test_init import ENV, PHONES, _db

COLUMNS = {"chats": {"whatsapp_id": "open", "phone_note": "quasi"}}


def _decl(verified: dict[str, list[str]]) -> Declaration:
    return Declaration.model_validate(
        {"dsn_env": ENV, "dialect": "sqlite", "entities": [], "columns": COLUMNS}
        | {"verified_open": verified}
    )


def test_verified_columns_are_left_out() -> None:
    samples: Samples = {("chats", "whatsapp_id"): [*PHONES], ("chats", "phone_note"): [*PHONES]}
    assert len(contradictions(_decl({}), samples)) == 2
    assert contradictions(_decl({"chats": ["whatsapp_id", "phone_note"]}), samples) == []


def test_contradictions_come_with_the_two_ways_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db, out = tmp_path / "w.db", tmp_path / "decl.yaml"
    _db(db)
    head = f"dsn_env: {ENV}\ndialect: sqlite\nentities: []\n"
    monkeypatch.setenv(ENV, f"sqlite:///{db.as_posix()}")
    argv = ["init", "--dsn-env", ENV, "--dialect", "sqlite", "--out", str(out)]
    out.write_text(head + "columns:\n  people: {id: open, ref: open}\n", encoding="utf-8")
    assert main(argv) == 0
    assert "list it under verified_open" in capsys.readouterr().out
    out.write_text(
        head + "columns:\n  people: {id: open, ref: open}\nverified_open: {people: [ref]}\n",
        encoding="utf-8",
    )
    assert main(argv) == 0
    seen = capsys.readouterr().out
    assert "contradictions: 0" in seen
    assert "verified_open" not in seen
