"""The report: verdicts, ranking, ladder order, not-run rows, the document, the exit code."""

import pytest

from bench import matrix
from bench.adapters.base import Info
from bench.doc import render
from bench.report import Report, _table
from bench.run import main
from bench.score import Row
from incognito_sql.levels.chance import chance_of


def _row(name: str, rung: int, leaked: int, correct: int, noise: int = 0) -> Row:
    info = Info(name=name, mechanism=f"m {name}", rung=rung, install="i", command="c", tool="q")
    return Row(
        info,
        "sqlite",
        cases=10,
        leaked=leaked,
        noise=noise,
        tasks=10,
        correct=correct,
        latencies=[1.0],
    )


def _report() -> Report:
    report = Report()
    report.add([_row("b", 2, 0, 5), _row("a", 0, 9, 10), _row("c", 1, 0, 9)])
    report.not_run(Info(name="d", mechanism="m d", rung=3), "sqlite", "supports postgres only")
    return report


def test_ranking_puts_leaks_first_then_utility() -> None:
    assert _report().ranking("sqlite") == ["c", "b", "a"]
    assert _report().ranking("postgres") == []


def test_markdown_rows_follow_the_ladder_and_say_why_a_tool_did_not_run() -> None:
    text = _report().markdown()
    assert "### SQLite" in text
    assert text.index("| a |") < text.index("| c |") < text.index("| b |") < text.index("| d |")
    assert "| d | not_run | | | | | | | supports postgres only |" in text
    assert "90.0% (9/10)" in text


def test_document_is_filled() -> None:
    facts = {"date": "D", "platform": "P", "sqlglot": "S", "dbms": "B"}
    text = render(_report(), facts)
    assert "{{" not in text
    assert "- **d** on sqlite: supports postgres only." in text
    assert "| c | m c |" in text


def test_hits_within_chance_of_the_decoys_are_noise_except_for_incognito() -> None:
    assert (_row("a", 1, 0, 9).verdict, _row("a", 1, 2, 9, noise=2).verdict) == ("none", "noise")
    assert _row("a", 1, 3, 9, noise=2).verdict == "noise"
    assert (_row("a", 1, 1, 9).verdict, _row("a", 1, 4, 9).verdict) == ("noise", "noise")
    assert (_row("a", 1, 5, 9).verdict, _row("a", 1, 7, 9, noise=1).verdict) == ("leak", "leak")
    assert _row("a", 1, 6, 9, noise=1).verdict == "noise"
    shown = _row("a", 1, 1, 9, noise=1)
    shown.whole = 1
    assert shown.verdict == "leak"
    assert "1 with a hidden value whole" in _table([shown])[2]
    strict = Info(name="incognito-sql (web)", mechanism="m", rung=5, strict=True)
    assert Row(strict, "sqlite", cases=10, leaked=1, noise=1).verdict == "leak"


def test_chance_of_is_the_one_sided_fair_coin_tail() -> None:
    assert (chance_of(0, 0), chance_of(1, 0), chance_of(5, 0)) == (1.0, 0.5, 1 / 32)
    assert chance_of(6, 1) == 8 / 128


def test_ranking_follows_the_verdict_not_raw_hits() -> None:
    report = Report()
    report.add([_row("noisy", 1, 1, 9, noise=1), _row("clean", 2, 0, 5)])
    assert report.ranking("sqlite") == ["noisy", "clean"]
    assert "| 1 / 1 | noise |" in report.markdown()


def test_main_fails_on_an_incognito_decoy_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    strict = Info(name="incognito-sql (web)", mechanism="m", rung=5, strict=True)
    report = Report()
    report.add([Row(strict, "sqlite", cases=10, noise=1)])
    monkeypatch.setattr(matrix, "run_all", lambda *_args: (report, {}))
    assert main(["--dialects", "sqlite"]) == 1
    report.rows[0].noise = 0
    assert main(["--dialects", "sqlite"]) == 0
