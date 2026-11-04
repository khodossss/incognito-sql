"""A SecureSQL condition on rows: the gateway's rule, the oracle, references, the twin."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from external_world import QUESTIONS, RECORDS, ROW_RECORDS, ROWS, build

from bench.adapters import launch
from bench.adapters.base import NotRunError
from bench.adapters.raw import RawAdapter
from bench.adapters.roster import COMPETITORS
from bench.dbms import Database
from bench.external import rows
from bench.external import tools as tool_rows
from bench.external.dbfile import opened
from bench.external.hidden import hidden_columns
from bench.external.marking import load
from bench.external.rowrule import RowRule
from bench.external.score import score
from bench.external.tally import Tally
from bench.external.tools import declaration, open_tools
from bench.external.twin import decoy_copy
from bench.external.work import Work, works
from incognito_sql.core.config import load_declaration

BRISA_TOTAL = "99.75"  # Brisa's only order: gone under the rule
AVEL_AGE = 41  # hidden in Avel's row


def _row_work(tmp_path: Path) -> tuple[Path, Work]:
    path, marking = build(tmp_path, rows=True)
    *_, work = works(path, marking, QUESTIONS, [*RECORDS, *ROW_RECORDS])
    assert work.marking.condition is not None
    assert work.marking.condition.text == ROWS
    return path, work


def test_a_condition_on_rows_is_read_as_the_gateway_s_rules(tmp_path: Path) -> None:
    _, marking = build(tmp_path, rows=True)
    (condition,) = (c for c in marking.conditions if c.rows)
    assert condition.columns == ()
    assert condition.rows == (
        RowRule("orders", (), "person_id = 2"),
        RowRule("people", ("age",), "id = 1"),
    )
    assert condition.rows[0].declared() == {
        "table": "orders",
        "hide": "*",
        "where": "person_id = 2",
    }
    assert ("people", "age") in marking.listed()
    assert marking.rules == ()  # in force only under the condition
    assert marking.under(condition).rules == condition.rows


def test_a_condition_that_closes_nothing_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("db: x\nset: spider\nconditions: [{text: Nothing.}]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="closes nothing"):
        load(path)


def test_the_rules_hide_cells_rows_and_nothing_else(tmp_path: Path) -> None:
    path, work = _row_work(tmp_path)
    copy = rows.masked_copy(path, tmp_path / "masked.sqlite", work.marking.rules)
    with opened(copy) as con:
        assert con.execute("SELECT id, age FROM people ORDER BY id").fetchall() == [
            (1, None),
            (2, 35),
            (3, 29),
            (4, 52),
        ]
        assert con.execute("SELECT count(*) FROM orders WHERE person_id = 2").fetchone() == (0,)
    with opened(path) as con:
        hidden = set(rows.cells(con, "orders", "total", work.marking.rules, hidden=True))
        shown = set(rows.cells(con, "orders", "total", work.marking.rules, hidden=False))
        assert hidden == {99.75}
        assert shown == {120.5, 80.0, 15.25}
        assert set(rows.cells(con, "people", "age", work.marking.rules, hidden=True)) == {41}


def test_a_null_condition_hides_as_the_gateway_does(tmp_path: Path) -> None:
    path = tmp_path / "n.sqlite"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE t (k INTEGER, v TEXT)")
        con.executemany("INSERT INTO t VALUES (?, ?)", [(1, "kept"), (None, "unknown")])
    con.close()
    rule = RowRule("t", ("v",), "k = 2")  # NULL for the second row: hidden
    with opened(path) as con:
        assert set(rows.cells(con, "t", "v", [rule], hidden=True)) == {"unknown"}
        assert set(rows.cells(con, "t", "v", [rule], hidden=False)) == {"kept"}


def test_the_work_under_rules_has_its_oracle_and_references(tmp_path: Path) -> None:
    _, work = _row_work(tmp_path)
    assert [(a.id, a.label) for a in work.attacks] == [("securesql-5", "DI")]
    expect = {t.id: t.expect for t in work.tasks}
    assert expect["securesql-6.0"] == ((3, 215.75),)  # Brisa's 99.75 is gone
    assert expect["securesql-7.0"] == ((1, None), (2, 35), (3, 29), (4, 52))
    assert work.oracle.found(f"total {BRISA_TOTAL}") == [BRISA_TOTAL]
    assert work.oracle.found("120.5") == []  # shown in its row
    assert ("orders", "total") not in hidden_columns(work.marking, work.schema)


def test_the_twin_replaces_only_what_the_rules_hide(tmp_path: Path) -> None:
    path, work = _row_work(tmp_path)
    twin = decoy_copy(
        path,
        tmp_path / "twin.sqlite",
        hidden_columns(work.marking, work.schema),
        work.marking.rules,
    )
    with opened(twin) as con:
        totals = dict(con.execute("SELECT id, total FROM orders").fetchall())
        ages = dict(con.execute("SELECT id, age FROM people").fetchall())
    assert totals[10] == 120.5
    assert 99.75 not in totals.values()  # the whole hidden row is replaced, its key too
    assert ages[2] == 35
    assert ages[1] != AVEL_AGE


def test_the_gateway_gets_the_rules_and_competitors_sit_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, work = _row_work(tmp_path)
    config = tmp_path / "decl.yaml"
    config.write_text(declaration(work, web=False), encoding="utf-8")
    assert [(r.table, r.where) for r in load_declaration(config).row_rules] == [
        ("orders", "person_id = 2"),
        ("people", "id = 1"),
    ]

    def no_docker(*_: object) -> str:
        msg = "docker is not installed"
        raise NotRunError(msg)

    monkeypatch.setattr(launch, "tool", no_docker)
    adapters, skipped = open_tools(work, tmp_path / "tools")
    for adapter in adapters:
        adapter.close()
    reasons = {info.name: reason for info, reason in skipped}
    for tool in COMPETITORS:
        if "sqlite" in tool.DIALECTS:
            assert reasons[tool.INFO.name] == "expresses no rule on rows"
    names = [a.info.name for a in adapters]
    assert names[0] == "raw"
    assert names[1:]
    assert all(n.startswith("incognito-sql (") for n in names[1:])  # a row per mode, profile


def _db(path: Path) -> Database:
    return Database("sqlite", f"sqlite:///{path.as_posix()}", path=path)


def test_raw_leaks_the_hidden_row_and_the_gateway_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the default profile: strict refuses sum() over a REAL column, a matter of profiles
    monkeypatch.setattr(tool_rows, "ROWS", ())
    path, work = _row_work(tmp_path)
    hidden = hidden_columns(work.marking, work.schema)
    twin = decoy_copy(path, tmp_path / "twin.sqlite", hidden, work.marking.rules)
    raw, control = RawAdapter(_db(path)), RawAdapter(_db(twin))
    tally = Tally(raw.info)
    try:
        score((raw, control), work, tally)
    finally:
        raw.close()
        control.close()
    assert (tally.attacks, tally.leaked) == (1, 1)
    assert tally.correct["securesql"] == 0  # raw sees the hidden row and cell
    tools, _ = open_tools(work, tmp_path / "ours")
    twins, _ = open_tools(replace(work, path=twin), tmp_path / "twin")
    try:
        for ours, theirs in zip(tools[1:], twins[1:], strict=True):
            mine = Tally(ours.info)
            score((ours, theirs), work, mine)
            assert (mine.leaked, mine.exposed) == (0, 0), ours.info.name
            assert mine.correct["securesql"] == 2, ours.info.name
    finally:
        for adapter in [*tools, *twins]:
            adapter.close()
