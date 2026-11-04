"""L2 in the score, claims and verdicts, and the table by level."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from external_world import QUESTIONS, RECORDS, build

from bench.adapters.base import Outcome
from bench.adapters.incognito import INFOS
from bench.adapters.raw import INFO, RawAdapter
from bench.adapters.roster import COMPETITORS
from bench.dbms import Database
from bench.external.claims import ours_broken, verdict
from bench.external.hidden import hidden_columns
from bench.external.levels import hours, levels
from bench.external.report import table
from bench.external.score import score
from bench.external.tally import Tally
from bench.external.twin import decoy_copy
from bench.external.work import works
from bench.profiles import (
    CLAIMS,
    INCOGNITO,
    MASKING,
    NO_BUDGET,
    NONE,
    Claim,
    claim_of,
    measured,
    ours,
    row_name,
)
from incognito_sql.levels.series import Result
from incognito_sql.levels.target import Target

MASKED = replace(INFO, name="halving", rung=1)


class Halving(RawAdapter):
    """Raw SQL that shows the first two thirds of every text cell: a part of each value."""

    def query(self, sql: str) -> Outcome:
        out = super().query(sql)
        if out.rows is None:
            return out
        rows = [[c[: len(c) * 2 // 3] if isinstance(c, str) else c for c in r] for r in out.rows]
        return Outcome(out.status, str(rows), out.ms, rows)


def _db(path: Path) -> Database:
    return Database("sqlite", f"sqlite:///{path.as_posix()}", path=path)


@pytest.fixture
def halving(tmp_path: Path) -> Tally:
    path, marking = build(tmp_path)
    tally = Tally(MASKED)
    adapter = Halving(_db(path), MASKED)
    for i, work in enumerate(works(path, marking, QUESTIONS, RECORDS)):
        copy = decoy_copy(
            path, tmp_path / f"twin-{i}.sqlite", hidden_columns(work.marking, work.schema)
        )
        control = Halving(_db(copy), MASKED)
        score((adapter, control), work, tally)
        control.close()
    adapter.close()
    return tally


def test_a_part_of_a_value_is_l2_not_l1(halving: Tally) -> None:
    assert halving.exposed == 0
    assert halving.partial_exposed == 1  # spider-0 shows two thirds of every name
    assert (halving.leaked, halving.partial) == (1, 0)  # numbers are not cut: totals whole


def test_claims_by_tool() -> None:
    assert claim_of(INFO) is NONE
    assert claim_of(MASKED).label() == "L1 (no claim)"  # a tool whose docs we did not read
    for tool in COMPETITORS:
        claim = claim_of(tool.INFO)
        assert claim.source, tool.INFO.name  # every claim cites the tool's own words
    gate = claim_of(next(t.INFO for t in COMPETITORS if t.INFO.name == "gate"))
    assert gate.label() == "L1"
    sanitized = next(t.INFO for t in COMPETITORS if t.INFO.name == "sanitized-db-mcp")
    assert claim_of(sanitized).label() == "L3"  # hidden columns refused in predicates
    assert claim_of(sanitized).series  # above L1: a value read whole by a series breaks it
    assert claim_of(INFOS["web"]) is INCOGNITO  # no profile named: the server's default
    assert INCOGNITO is CLAIMS["permissive"]
    assert INCOGNITO.label() == "L3 but existence, order, length, prefix, contains"
    assert CLAIMS["strict"].label() == "L3 but existence"
    assert MASKING.label() == "L1"
    assert Claim("L3", frozenset()).label() == "L3"
    by_profile = replace(INFOS["labels"], name=row_name("incognito-sql (labels)", "permissive"))
    assert by_profile.name == "incognito-sql (labels, permissive)"
    assert claim_of(by_profile) is INCOGNITO
    assert claim_of(replace(by_profile, name="incognito-sql (web, strict)")) is CLAIMS["strict"]


def test_a_row_with_the_budget_lifted_is_a_measure_with_no_claim() -> None:
    lifted = replace(
        INFOS["labels"], name=row_name("incognito-sql (labels, permissive)", NO_BUDGET)
    )
    assert lifted.name == "incognito-sql (labels, permissive, no budget)"
    assert measured(lifted)
    assert not measured(INFOS["labels"])
    assert claim_of(lifted) is NONE
    assert not ours_broken(Tally(lifted, leaked=1, attacks=1))


def test_hours_at_the_default_budgets() -> None:
    assert hours([]) == "-"
    assert hours([(20, 0)]) == "0"  # the first window is free
    assert hours([(41, 0), (30, 0), (70, 0)]) == "2"  # median 41: three windows of 20
    assert hours([(0, 250)]) == "2"  # 250 probes: three windows of 100
    assert hours([(41, 101)]) == "2"  # the slower budget sets the wait


def test_our_claims_come_from_the_server() -> None:
    assert ours({"p": ["L3 order"]}) == {"p": Claim("L3", frozenset({"order"}), series=True)}
    for leaks in (["L2 partial_output"], ["L3 timing"]):
        with pytest.raises(ValueError, match="does not judge"):
            ours({"p": leaks})


def _inferred(tally: Tally, channel: str) -> Tally:
    target = Target("people", "id", 1, "full_name", "Avel Quorin")
    tally.inference.add(Result(channel, target, claim="11" if channel == "length" else "ave"))
    tally.inference.settle()
    return tally


def test_verdicts_against_the_claim() -> None:
    partial = Tally(MASKED, cut_part=1)
    assert verdict(partial, NONE) == "no claim"
    assert verdict(partial, MASKING).startswith("holds L1")
    assert verdict(partial, Claim("L2")) == "breaks L2"
    strict = CLAIMS["strict"]
    assert verdict(Tally(MASKED), strict) == "holds"
    assert verdict(_inferred(Tally(MASKED), "length"), strict) == "breaks L3 (length)"
    assert verdict(_inferred(Tally(MASKED), "length"), INCOGNITO) == "holds"  # declared open
    assert verdict(Tally(MASKED, cut_part=1), INCOGNITO) == "breaks L2"  # no part in output
    leaky = Tally(MASKED, leaked=1)
    assert verdict(leaky, MASKING) == "breaks L1"
    read = Tally(MASKED)
    read.inference.whole = 1  # a series read a value whole
    assert verdict(read, MASKING).startswith("holds L1")  # masking: one level, not claimed
    assert verdict(read, INCOGNITO) == "breaks L1"


def test_the_table_by_level(halving: Tally) -> None:
    _inferred(halving, "prefix")
    text = levels([halving, Tally(replace(INFO, name="idle", rung=2))])
    # head, tail and split cut two thirds again; MIN/MAX shows two thirds of a value
    row = "| halving | L1 (no claim) | 100.0% (1/1) | 0.0% (0/3) | 0.0% (0/1) | 50.0% (6/12) | - |"
    assert row in text
    assert "| 100% (1/1) | - | breaks L1 |" in text
    assert "idle" not in text
    assert "L2 e.g. `spider-0`" in table([halving])


def test_cuts_are_four_valid_queries_per_hidden_column(tmp_path: Path) -> None:
    path, marking = build(tmp_path)
    work = next(works(path, marking, QUESTIONS, RECORDS))
    names = [case.id for case in work.cuts]
    assert names[:4] == [
        "orders.note:head",
        "orders.note:tail",
        "orders.note:split",
        "orders.note:minmax",
    ]
    assert len(names) == 12  # note, email, full_name
    with closing(sqlite3.connect(path)) as con:
        rows = [con.execute(case.queries[0]).fetchall() for case in work.cuts]
    assert rows[0] == [("gift w",), ("rush",)]  # six characters at least
    assert ("gift  | wrap",) in rows[2]


def test_the_run_fails_when_incognito_sql_breaks_l1() -> None:
    ours = Tally(INFOS["web"])
    assert not ours_broken(ours)
    ours.inference.whole = 1
    assert ours_broken(ours)
    assert not ours_broken(Tally(MASKED, leaked=1))  # a competitor's leak is reported, not fatal
