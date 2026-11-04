"""Random queries: reproducible, varied, and on SQLite none of them leaks through the gateway."""

import random
from pathlib import Path

import pytest
import yaml

from bench.adapters.base import Outcome
from bench.adapters.incognito import IncognitoAdapter
from bench.fuzz import run as fuzz_run
from bench.fuzz.grammar import Grammar
from bench.fuzz.run import Finding, Tally, fuzz
from bench.harness import MODES, Run
from bench.schema import DIALECTS
from bench.world import World

SHAPES = (
    " UNION ",
    "WITH t AS",
    " JOIN ",
    "CAST(",
    "CASE WHEN",
    "EXISTS (",
    " GROUP BY ",
    " ORDER BY ",
    "COUNT(DISTINCT",
    "{{TOKEN_OWN}}",
    "(SELECT MAX(",
    "a.password_hash",
    "a.ssn",
)


def _queries(seed: int, dialect: str, count: int) -> list[str]:
    grammar = Grammar(random.Random(seed), dialect)  # noqa: S311 -- reproducible
    return [grammar.query() for _ in range(count)]


def test_the_same_seed_gives_the_same_queries() -> None:
    assert _queries(5, "postgres", 50) == _queries(5, "postgres", 50)
    assert _queries(5, "postgres", 50) != _queries(6, "postgres", 50)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_queries_cover_the_shapes_and_columns(dialect: str) -> None:
    text = "\n".join(_queries(1, dialect, 600))
    missing = [s for s in SHAPES if s not in text]
    assert missing == []
    assert (" LIMIT " in text) is (dialect != "tsql")


@pytest.mark.no_cover
def test_random_queries_do_not_leak_on_sqlite(runs: dict[str, Run], world: World) -> None:
    adapters = [IncognitoAdapter(runs[mode], mode, "sqlite") for mode in MODES]
    tally = fuzz(adapters, world.planted("sqlite"), seed=3, count=300)
    assert tally.findings == []
    answered = sum(v for k, v in tally.statuses.items() if k.endswith(":answered"))
    assert answered > tally.sent // 5  # the answers, where a leak would show, are many


class _Leaky:
    """An adapter whose answer carries a hidden value: the oracle must flag it."""

    mode, dialect, tokens = "web", "sqlite", {"TOKEN_OWN": "tk_aaaaaaaaaaaaaaaa"}

    def __init__(self, canary: str) -> None:
        self._canary = canary

    def query(self, _sql: str) -> Outcome:
        return Outcome("answered", f'{{"rows": [["{self._canary}"]]}}', 1.0)

    def channels(self) -> dict[str, str]:
        return {"audit": ""}


def test_a_leaking_answer_is_a_finding(world: World) -> None:
    canary = min(world.planted("sqlite"))
    tally = fuzz([_Leaky(canary)], world.planted("sqlite"), seed=1, count=2)  # type: ignore[list-item]
    assert [(f.index, f.canaries) for f in tally.findings] == [(0, [canary]), (1, [canary])]


def test_main_writes_findings_and_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    finding = Finding("sqlite", "web", 1, 0, "SELECT 1", ["Zqx"])
    tallies = {"sqlite": Tally(sent=2, findings=[finding]), "duckdb": Tally(sent=2)}
    monkeypatch.setattr(fuzz_run, "run_on", lambda dialect, _seed, _count: tallies[dialect])
    out = tmp_path / "found.yaml"
    argv = ["--dialects", "sqlite", "duckdb", "--count", "1", "--out", str(out)]
    assert fuzz_run.main(argv) == 1
    assert yaml.safe_load(out.read_text(encoding="utf-8"))[0]["sql"] == "SELECT 1"
    assert "sqlite: 2 sent" in capsys.readouterr().out
    del tallies["sqlite"]
    assert fuzz_run.main(["--dialects", "duckdb", "--out", str(tmp_path / "none.yaml")]) == 0


def test_a_crashed_dbms_keeps_the_findings_before_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    finding = Finding("sqlite", "web", 1, 0, "SELECT 1", ["Zqx"])

    def run_on(dialect: str, _seed: int, _count: int) -> Tally:
        if dialect == "mysql":
            raise RuntimeError
        return Tally(sent=1, findings=[finding] if dialect == "sqlite" else [])

    monkeypatch.setattr(fuzz_run, "run_on", run_on)
    out = tmp_path / "found.yaml"
    assert fuzz_run.main(["--dialects", "sqlite", "mysql", "--out", str(out)]) == 1
    assert out.exists()
    assert fuzz_run.main(["--dialects", "duckdb", "mysql", "--out", str(tmp_path / "x")]) == 2
