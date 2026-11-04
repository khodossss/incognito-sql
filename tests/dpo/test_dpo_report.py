"""`report` over a real audit log of an invented database: counts by column, never a value."""

import base64
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from incognito_sql.cli import main
from incognito_sql.core.config import load_declaration
from incognito_sql.wiring import audit_path, open_gateway

KEY = bytes(range(32))
PEOPLE = [(1, "Avel Quorin", "zqnote one"), (2, "Brisa Tolland", "zqnote two")]  # invented
SCHEMA_NAMES = ("people.full_name", "people.notes", "people.id", "people")
CONFIG = """dsn_env: REPORT_DSN
dialect: sqlite
columns:
  people: {id: open, full_name: identifier}
entities:
  - {table: people, pk: id}
"""


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "people.db"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT, notes TEXT)")
        con.executemany("INSERT INTO people VALUES (?, ?, ?)", PEOPLE)
        con.commit()
    monkeypatch.setenv("INCOGNITO_SQL_KEY", base64.b64encode(KEY).decode("ascii"))
    path = tmp_path / "field.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    gateway = open_gateway(path, load_declaration(path), f"sqlite:///{db.as_posix()}", KEY)
    try:
        gateway.query("SELECT id, full_name FROM people", "c1")
        gateway.query("SELECT id FROM people WHERE full_name = 'Avel Quorin'", "c1")
        gateway.query("SELECT notes FROM people", "c1")  # hidden: refused
        gateway.query("SELEC notes FROM people", "c1")  # refused before naming a column
    finally:
        gateway.close()
    with audit_path(path).open("a", encoding="utf-8") as fh:  # a line from an older version
        fh.write(json.dumps({"ts": "2026-09-01T10:00:00+00:00", "outcome": "ok"}) + "\n")
        fh.write("not json\n")
        computed = {  # a naive time, upper-case names, a mask of a computed column
            "ts": "2026-11-01T10:00:00",
            "outcome": "ok",
            "columns": ["PEOPLE.FULL_NAME"],
            "masked": ["a computed result column over people: email"],
        }
        fh.write(json.dumps(computed) + "\n")
    return path


def _report(config: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, Any]:
    assert main(["report", "--config", str(config), "--json", "--since", "all", *extra]) == 0
    out = capsys.readouterr()
    text = (out.out + out.err).casefold()
    assert "select" not in text  # no query, not even tokenized
    for schema in SCHEMA_NAMES:
        text = text.replace(schema, " ")
    for _, name, note in PEOPLE:
        for value in (name, note):
            pieces = {value[i : i + 4] for i in range(len(value) - 3)}
            for piece in (p for p in pieces if p.isalnum()):  # spaces join report words
                assert piece.casefold() not in text, piece
    report: dict[str, Any] = json.loads(out.out)
    return report


def test_each_column_with_its_claim_and_what_was_asked(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _report(config, capsys)
    rows = {r["column"]: r for r in report["columns"]}
    assert list(rows) == ["people.full_name", "people.id", "people.notes"]
    name = rows["people.full_name"]
    assert name["class"] == "identifier"
    assert name["profile"] == "permissive"
    assert "facts by a series: contains, existence" in name["the model may learn"]
    assert (name["queries naming it"], name["outcomes"]) == ("3", "ok 3")
    assert name["answers with masked cells"] == "-"
    notes = rows["people.notes"]
    assert notes["class"] == "hidden (not in the config)"
    assert notes["outcomes"] == "rejected: hidden_column 1"
    assert report["queries"] == 6
    assert report["queries before the log named columns"] == 1
    assert report["queries refused before naming a column"] == 1
    assert report["answers with masked computed columns"] == {"email": 1}
    assert report["probes spent"] == 0  # = with a literal is no probe
    assert report["queries before the log counted probes"] == 2
    assert report["unreadable lines (any date)"] == 1


def test_an_assess_report_is_merged_by_column(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assessed = config.parent / "assess.json"
    assessed.write_text(
        json.dumps(
            {
                "columns": [{"column": "people.full_name", "verdict": "holds", "L2 cuts": "0/4"}],
                "hidden": [{"column": "PEOPLE.NOTES", "hidden: refused": "4/4"}],
                "capacity": [
                    {
                        "column": "people.full_name",
                        "verdict": "breaks L3 (length)",
                        "hours whole": "13",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rows = {r["column"]: r for r in _report(config, capsys, "--assess", str(assessed))["columns"]}
    assert rows["people.full_name"]["measured"] == (
        "verdict holds; L2 cuts 0/4; budget lifted: verdict breaks L3 (length); hours whole 13"
    )
    assert rows["people.notes"]["measured"] == "hidden: refused 4/4"
    assert rows["people.id"]["measured"] == "-"


def test_the_period_is_the_last_30_days_by_default(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", "--config", str(config)]) == 0
    text = capsys.readouterr().out
    assert "(the last 30 days)" in text
    assert "- queries: 5" in text  # the older line is outside the period
    assert main(["report", "--config", str(config), "--since", "not-a-date"]) == 2
    assert "report:" in capsys.readouterr().err


def test_a_log_it_may_not_read_is_said_in_a_line(
    config: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(*_: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("incognito_sql.dpo.command.read", denied)
    assert main(["report", "--config", str(config)]) == 2
    assert capsys.readouterr().err.startswith("incognito-sql: report: ")


def test_probes_are_summed_over_the_lines_that_count_them(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with audit_path(config).open("a", encoding="utf-8") as fh:
        line = {"ts": "2026-11-02T10:00:00+00:00", "outcome": "ok", "columns": [], "probes": 3}
        fh.write(json.dumps(line) + "\n")
    report = _report(config, capsys)
    assert report["probes spent"] == 3
    assert report["queries before the log counted probes"] == 2


def test_the_text_report_names_the_hours_words(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assessed = config.parent / "assess.json"
    lifted = {"column": "people.full_name", "verdict": "holds", "hours whole": "closed"}
    assessed.write_text(json.dumps({"capacity": [lifted]}), encoding="utf-8")
    args = ["report", "--config", str(config), "--since", "all", "--assess", str(assessed)]
    assert main(args) == 0
    legend = capsys.readouterr().out.rsplit("hours:", 1)[-1]
    assert all(word in legend for word in ("-", "closed", "unlimited"))
