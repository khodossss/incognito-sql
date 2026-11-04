"""`assess` on an invented database: counts per column, no value, the service's files kept."""

import base64
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from incognito_sql.assess import truth
from incognito_sql.assess.command import EXIT_FAILED
from incognito_sql.assess.model import Assessment, ColumnLevels, HiddenColumn
from incognito_sql.assess.report import as_text, broken
from incognito_sql.cli import main
from incognito_sql.wiring import open_gateway

KEY = base64.b64encode(bytes(range(32))).decode("ascii")
PEOPLE = [  # invented
    (1, "Avel Quorin", "avel.quorin@example.test"),
    (2, "Brisa Tolland", "brisa.tolland@example.test"),
    (3, "Corwin Ashe", "corwin.ashe@example.test"),
    (4, "Dalia Fenwick", "dalia.fenwick@example.test"),
]
SCHEMA_NAMES = ("people.full_name", "people.email", "people.notes", "people", "email")
CONFIG = """dsn_env: ASSESS_DSN
dialect: sqlite
protection: {profile}
columns:
  people: {{id: open, full_name: identifier, email: identifier}}
entities:
  - {{table: people, pk: id}}
"""


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "people.db"
    with closing(sqlite3.connect(db)) as con:
        con.execute(
            "CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT, email TEXT, notes TEXT)"
        )
        con.executemany("INSERT INTO people VALUES (?, ?, ?, 'zqnote')", PEOPLE)
        con.commit()
    monkeypatch.setenv("ASSESS_DSN", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("INCOGNITO_SQL_KEY", KEY)
    return tmp_path / "field.yaml"


def _run(
    config: Path, profile: str, capsys: pytest.CaptureFixture[str], *extra: str, limits: str = ""
) -> dict[str, Any]:
    config.write_text(CONFIG.format(profile=profile) + limits, encoding="utf-8")
    code = main(["assess", "--config", str(config), "--json", "--fail-on", "breaks", *extra])
    out = capsys.readouterr()
    text = (out.out + out.err).casefold()
    for schema in sorted(SCHEMA_NAMES, key=len, reverse=True):  # names, not values
        text = text.replace(schema, " ")
    for _, name, email in PEOPLE:  # never a value, nor a piece of one of 4 characters
        for value in (name, email):
            for piece in {value[i : i + 4] for i in range(len(value) - 3)}:
                assert piece.casefold() not in text, piece
    report: dict[str, Any] = json.loads(out.out)
    report["code"] = code
    return report


def test_strict_holds_and_the_service_files_are_left_alone(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _run(config, "strict", capsys)
    assert report["code"] == 0
    rows = {r["column"]: r for r in report["columns"]}
    assert set(rows) == {"people.email", "people.full_name"}
    assert {r["verdict"] for r in rows.values()} == {"holds"}
    assert rows["people.full_name"]["L1 cuts"] == "0/4"
    assert rows["people.full_name"]["L3 prefix"] == "0% (0/3)"
    assert report["capacity"] == []
    assert report["hidden"] == [
        {"column": "people.notes", "hidden: refused": "4/4", "verdict": "holds"}
    ]
    assert sorted(p.name for p in config.parent.iterdir()) == ["field.yaml", "people.db"]


def test_capacity_reads_what_permissive_opens_with_the_budget_lifted(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _run(config, "permissive", capsys, "--capacity", "--targets", "2")
    lifted = {r["column"]: r for r in report["capacity"]}
    # read whole with the budget lifted is the channel's capacity, not a broken claim
    assert lifted["people.full_name"]["L1 series"] != "0/2"
    assert lifted["people.full_name"]["verdict"] == "holds"
    assert lifted["people.full_name"]["hours whole"] not in {"-", None}  # at the config's budget
    assert "hours whole" not in report["columns"][0]


def test_a_failure_names_its_type_never_the_probe_it_carried(
    config: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(*_: object) -> bool:
        statement = "SELECT ..."
        raise OperationalError(statement, (1, "Avel Quorin"), Exception("timeout"))

    monkeypatch.setattr(truth.DbTruth, "below", failing)
    config.write_text(CONFIG.format(profile="strict"), encoding="utf-8")
    assert main(["assess", "--config", str(config)]) == EXIT_FAILED
    out = capsys.readouterr()
    assert out.err == "incognito-sql: assess failed: OperationalError\n"
    assert "avel" not in (out.out + out.err).casefold()


def test_every_column_gets_a_budget_of_its_own(
    config: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[Path] = []

    def counting(path: Path, *rest: Any) -> Any:  # noqa: ANN401 -- passes its arguments on
        opened.append(path)
        return open_gateway(path, *rest)

    monkeypatch.setattr("incognito_sql.assess.run.open_gateway", counting)
    _run(config, "strict", capsys)
    assert len(opened) == 3  # the hidden columns' cuts, then one per identifier column
    assert len({p.parent for p in opened}) == 3


def test_a_column_with_no_value_to_probe_is_not_called_held(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with closing(sqlite3.connect(config.parent / "people.db")) as con:
        con.execute("UPDATE people SET email = 'x'")
        con.commit()
    rows = {r["column"]: r for r in _run(config, "strict", capsys)["columns"]}
    assert rows["people.email"]["verdict"] == "holds cuts; no value to probe by a series"


def test_a_hole_in_the_policy_is_a_broken_claim(
    config: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("incognito_sql.core.sql.policy.check_mentions", lambda *_, **__: None)
    report = _run(config, "strict", capsys)
    assert report["code"] == 1
    rows = [*report["columns"], *report["hidden"]]
    assert any(r["verdict"].startswith("breaks") for r in rows)


def test_broken_reads_the_verdicts_under_the_default_budget() -> None:
    held = ColumnLevels("people", "full_name", "strict", frozenset())
    shown = ColumnLevels("people", "email", "strict", frozenset(), cuts=4, whole=1)
    measured = ColumnLevels("people", "email", "strict", frozenset(), measure=True)
    assert not broken(Assessment([held], [measured]))
    assert broken(Assessment([held, shown], []))
    assert broken(Assessment([held], [shown]))  # a hole the budget hid breaks too
    assert shown.verdict() == "breaks L1"
    assert "| people.email | strict |" in as_text(Assessment([shown], []))
    answered = HiddenColumn("people", "notes", cuts=4, refused=3)
    assert answered.verdict() == "breaks: 1 answered"
    assert broken(Assessment([held], [], [answered]))


@pytest.mark.parametrize(
    ("limits", "hours"),
    [
        ("limits: {literal_budget: unlimited, probe_budget: unlimited}\n", "unlimited"),
        ("limits: {literal_budget: 0}\n", "closed"),
    ],
)
def test_hours_read_the_operators_budgets_as_given(
    config: Path, capsys: pytest.CaptureFixture[str], limits: str, hours: str
) -> None:
    report = _run(config, "permissive", capsys, "--capacity", "--targets", "1", limits=limits)
    lifted = {r["column"]: r for r in report["capacity"]}
    assert lifted["people.full_name"]["hours whole"] == hours
    if hours == "closed":  # literals off: no series under the config's own budget reads a value
        held = {r["column"]: r for r in report["columns"]}
        assert held["people.full_name"]["L1 series"] == "0/1"


def test_the_capacity_table_names_its_three_words() -> None:
    held = ColumnLevels("people", "full_name", "permissive", frozenset())
    lifted = ColumnLevels("people", "full_name", "permissive", frozenset(), measure=True)
    text = as_text(Assessment([held], [lifted]))
    legend = text.rsplit("hours:", 1)[-1]
    assert all(word in legend for word in ("-", "closed", "unlimited"))
    assert "hours:" not in as_text(Assessment([held], []))
