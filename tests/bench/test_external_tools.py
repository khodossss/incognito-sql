"""Tools on a set's file: raw SQL's row cap, incognito-sql's declaration, the roster."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from external_world import QUESTIONS, RECORDS, build

from bench.adapters import launch
from bench.adapters.base import NotRunError
from bench.adapters.roster import COMPETITORS
from bench.dbms import Database
from bench.external import replay
from bench.external.containers import OPENERS
from bench.external.dbfile import MAX_ROWS
from bench.external.tools import CappedRaw, declaration, open_tools
from bench.external.work import works
from bench.harness import MODES
from bench.profiles import PROFILES
from incognito_sql.core.config import load_declaration


def test_raw_sql_keeps_the_first_rows_of_a_long_answer(tmp_path: Path) -> None:
    path = tmp_path / "long.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (n INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(MAX_ROWS + 5)])
    con.commit()
    con.close()
    raw = CappedRaw(Database("sqlite", f"sqlite:///{path.as_posix()}", path=path))
    try:
        long, short = raw.query("SELECT n FROM t ORDER BY n"), raw.query("SELECT 1")
    finally:
        raw.close()
    assert long.rows == [[i] for i in range(MAX_ROWS)]
    assert json.loads(long.text) == long.rows
    assert short.rows == [[1]]


def test_verified_columns_reach_the_declaration_while_shown(tmp_path: Path) -> None:
    path, marking = build(tmp_path)
    marking = replace(marking, verified_open=(("orders", "total"), ("people", "id")))
    seen = []
    for i, work in enumerate(works(path, marking, QUESTIONS, RECORDS)):
        config = tmp_path / f"decl-{i}.yaml"
        config.write_text(declaration(work, web=False), encoding="utf-8")
        seen.append(load_declaration(config).verified_open)
    assert {"orders": ["total"], "people": ["id"]} in seen  # no condition: both shown
    assert {"people": ["id"]} in seen  # the condition closes orders.total


def test_the_series_keeps_the_literal_budget_and_a_profile_is_named(tmp_path: Path) -> None:
    path, marking = build(tmp_path)
    work = next(works(path, marking, QUESTIONS, RECORDS))
    assert "literal_budget" in declaration(work, web=False)
    series = yaml.safe_load(declaration(work, web=False, series=True, profile="strict"))
    assert series["limits"] == {"query_rate": 10**6}  # the default literal budget stops it
    assert series["protection"] == "strict"


def _no_docker(*_: object) -> str:
    msg = "docker is not installed"
    raise NotRunError(msg)


def test_every_competitor_runs_on_sqlite_or_says_why_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, marking = build(tmp_path)
    monkeypatch.setattr(launch, "tool", _no_docker)
    work = next(iter(works(path, marking, QUESTIONS, RECORDS)))
    adapters, skipped = open_tools(work, tmp_path / "tools")
    for adapter in adapters:
        adapter.close()
    reasons = {info.name: reason for info, reason in skipped}
    assert len(reasons) == len(COMPETITORS)
    for tool in COMPETITORS:
        sqlite = "sqlite" in tool.DIALECTS
        assert (tool in OPENERS) == sqlite
        expected = "docker is not installed" if sqlite else "only"
        assert expected in reasons[tool.INFO.name]
    incognito = [f"incognito-sql ({mode}, {profile})" for profile in PROFILES for mode in MODES]
    assert sorted(a.info.name for a in adapters) == sorted(["raw", *incognito])


def test_a_recorded_competitor_is_replayed_without_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, marking = build(tmp_path)
    monkeypatch.setattr(launch, "tool", _no_docker)
    work = next(iter(works(path, marking, QUESTIONS, RECORDS)))
    store = replay.Store(tmp_path / "replay.sqlite")
    sqlite = [t for t in COMPETITORS if "sqlite" in t.DIALECTS]
    store.put(replay.key(sqlite[0].INFO, "twin", work), "static", "", "listing")
    adapters, skipped = open_tools(work, tmp_path / "tools", store, "twin")
    names = [a.info.name for a in adapters]
    for adapter in adapters:
        adapter.close()
    store.close()
    assert sqlite[0].INFO.name in names
    assert len(skipped) == len(COMPETITORS) - 1


def test_incognito_answers_are_kept_and_read_back_while_the_server_is_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, marking = build(tmp_path)
    monkeypatch.setattr(launch, "tool", _no_docker)
    work = next(iter(works(path, marking, QUESTIONS, RECORDS)))
    sql = "SELECT count(*) FROM customers"

    def ask(store: replay.Store) -> list[str]:
        adapters, _ = open_tools(work, tmp_path / "tools", store)
        try:
            return [a.query(sql).text for a in adapters if a.info.strict]
        finally:
            for adapter in adapters:
                adapter.close()

    store = replay.Store(tmp_path / "replay.sqlite")
    first = ask(store)
    store.close()
    rescore = replay.Store(tmp_path / "replay.sqlite", rescore=True)
    assert ask(rescore) == first  # every incognito row, read back without the server
    adapters, _ = open_tools(work, tmp_path / "tools", rescore)
    try:
        with pytest.raises(replay.UnrecordedError):
            next(a for a in adapters if a.info.strict).query("SELECT 1")
    finally:
        for adapter in adapters:
            adapter.close()
        rescore.close()
