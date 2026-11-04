"""The benchmark end to end on SQLite: incognito-sql, a tool that leaks, and raw SQL.

The report must tell them apart: the leaking tool and the unprotected control rank
below incognito-sql, and incognito-sql shows no leak under attack or honest use.
"""

import re
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from bench.adapters.base import ANSWERED, Outcome
from bench.adapters.incognito import INFOS, IncognitoAdapter, open_incognito, profile_infos
from bench.adapters.raw import INFO, RawAdapter
from bench.cases import load_cases
from bench.dbms import Database
from bench.profiles import PROFILES, row_name
from bench.report import Report
from bench.run import breaks_claim, run
from bench.score import Row
from bench.tasks import load_tasks
from bench.world import World

CANARY = re.compile(r"Zq\w{10}", re.IGNORECASE)


class LeakyAdapter(RawAdapter):
    """Masks every canary in its answers, but logs the raw answer to stderr."""

    def __init__(self, db: Database) -> None:
        super().__init__(db, INFO.__class__(**{**INFO.__dict__, "name": "leaky", "rung": 1}))
        self._log = ""

    def query(self, sql: str) -> Outcome:
        out = super().query(sql)
        self._log = out.text
        masked = CANARY.sub("***", out.text)
        return Outcome(out.status, masked, out.ms, out.rows)

    def channels(self) -> dict[str, str]:
        log, self._log = self._log, ""
        return {"stderr": log}


@pytest.fixture(scope="module")
def database(world_db: Path) -> Database:
    return Database("sqlite", f"sqlite:///{world_db.as_posix()}", path=world_db)


@pytest.fixture(scope="module")
def incognito(
    world: World, database: Database, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[list[IncognitoAdapter]]:
    opened = open_incognito(world, database, tmp_path_factory.mktemp("smoke"))
    yield opened
    for adapter in opened:
        adapter.close()


@pytest.fixture(scope="module")
def report(world: World, database: Database, incognito: list[IncognitoAdapter]) -> Report:
    leaky, raw = LeakyAdapter(database), RawAdapter(database)
    corpus = load_cases()[::6]  # a slice: the whole corpus runs in test_corpus
    try:
        return run([*incognito, leaky, raw], corpus, load_tasks(), world)
    finally:
        leaky.close()
        raw.close()


def test_report_ranks_the_leaking_tool_below_incognito(report: Report) -> None:
    ranking = report.ranking("sqlite")
    assert ranking[:2] == ["incognito-sql (web)", "incognito-sql (labels)"] or ranking[:2] == [
        "incognito-sql (labels)",
        "incognito-sql (web)",
    ]
    assert set(ranking[2:]) == {"leaky", "raw"}


def test_incognito_leaks_nothing_and_answers(report: Report) -> None:
    for row in report.rows:
        if row.info.name.startswith("incognito"):
            assert (row.leaked, row.exposed, row.cases > 50) == (0, 0, True), row.info.name
            assert row.utility > 0.8, row.info.name


def test_the_leak_is_found_in_a_side_channel_and_raw_is_the_positive_control(
    report: Report,
) -> None:
    rows = {row.info.name: row for row in report.rows}
    assert rows["leaky"].attacker_success > 0.1
    assert rows["raw"].attacker_success > 0.1
    assert rows["raw"].utility == 1.0  # every hand-labelled answer holds on the world
    assert rows["raw"].over_exposure > 0


def test_markdown_has_a_row_per_tool(report: Report) -> None:
    text = report.markdown()
    for name in ("raw", "leaky", "incognito-sql (web)", "incognito-sql (labels)"):
        assert f"| {name} |" in text


def test_a_row_per_mode_and_profile(world: World, database: Database, tmp_path: Path) -> None:
    opened = open_incognito(world, database, tmp_path, PROFILES)
    try:
        names = [a.info.name for a in opened]
        assert names == [i.name for i in profile_infos(PROFILES)]
        assert names[:2] == ["incognito-sql (web, strict)", "incognito-sql (labels, strict)"]
        assert {a.query("SELECT tier FROM users").status for a in opened} == {ANSWERED}
    finally:
        for adapter in opened:
            adapter.close()


@pytest.mark.parametrize(
    ("profile", "whole", "broken"),
    # every ready profile claims L2 closed: a piece of a value breaks any of them
    [("strict", 0, True), ("balanced", 0, True), ("permissive", 0, True), ("permissive", 1, True)],
)
def test_a_row_of_ours_fails_the_run_when_it_breaks_its_profile_claim(
    profile: str, whole: int, *, broken: bool
) -> None:
    info = replace(INFOS["labels"], name=row_name(INFOS["labels"].name, profile))
    assert breaks_claim(Row(info, "sqlite", leaked=1, whole=whole)) is broken
    assert breaks_claim(Row(info, "sqlite", exposed=1)) is True
