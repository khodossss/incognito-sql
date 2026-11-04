"""The columns step reads init's scaffold and writes the decisions; change confirms what opens."""

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from incognito_sql.core.config import load_declaration
from incognito_sql.init.run import run_init
from incognito_sql.setup.columns import HIDDEN, Proposal, apply_classes, proposals
from incognito_sql.setup.widen import put_back_unless_confirmed, widenings

if TYPE_CHECKING:
    from incognito_sql.setup.model import Answers

ENV = "SETUP_TEST_DSN"


@pytest.fixture
def scaffold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db, out = tmp_path / "w.db", tmp_path / "w.yaml"
    with sqlite3.connect(db) as con:
        con.executescript(
            "CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT, ref TEXT, city TEXT);"
            "INSERT INTO people VALUES (1, 'Zqcanary Person', 'zqcanary@example.com', 'X');"
        )
    con.close()
    monkeypatch.setenv(ENV, f"sqlite:///{db.as_posix()}")
    assert run_init(ENV, "sqlite", out, use_sample=True) == 0
    return out


def test_proposals_follow_init_and_hold_no_value(scaffold: Path) -> None:
    found = {(p.table, p.column): p for p in proposals(scaffold)}
    assert found[("people", "full_name")] == Proposal(
        "people", "full_name", "identifier", 'name hint "name"'
    )
    assert found[("people", "ref")].reason == "sample looks personal"
    assert found[("people", "id")] == Proposal("people", "id", "open", "")
    assert found[("people", "city")].suggested == "quasi"
    assert "zqcanary" not in repr(found).lower()


def test_decisions_become_the_declaration(scaffold: Path) -> None:
    classes = {
        ("people", "id"): "open",
        ("people", "full_name"): "identifier",
        ("people", "ref"): HIDDEN,
        ("people", "city"): "quasi",
    }
    assert apply_classes(scaffold, classes, [("people", "id")]) is None
    decl = load_declaration(scaffold)
    assert decl.columns == {"people": {"id": "open", "full_name": "identifier", "city": "quasi"}}
    assert decl.dsn_env == ENV
    before = scaffold.read_text("utf-8")
    assert apply_classes(scaffold, classes, [("people", "nope")]) is not None
    assert scaffold.read_text("utf-8") == before  # a bad decision leaves the file


def test_a_widening_unconfirmed_is_put_back(scaffold: Path, tmp_path: Path) -> None:
    classes = {("people", "id"): "open", ("people", "full_name"): "identifier"}
    assert apply_classes(scaffold, classes, []) is None
    before = tmp_path / "w.before.yaml"
    before.write_text(scaffold.read_text("utf-8"), "utf-8")
    assert apply_classes(scaffold, {**classes, ("people", "city"): "open"}, []) is None
    assert widenings(before, scaffold) == ["WIDENED people.city: hidden -> open"]
    answers: Answers = {"config": str(scaffold), "widened": ["no"]}
    put_back_unless_confirmed(answers)
    assert scaffold.read_text("utf-8") == before.read_text("utf-8")
