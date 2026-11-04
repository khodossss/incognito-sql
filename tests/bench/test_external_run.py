"""The independent-sets run end to end on the invented shop: raw leaks, incognito-sql not."""

from pathlib import Path

import pytest
from external_world import QUESTIONS, RECORDS, build

from bench.adapters.base import NotRunError
from bench.external import inputs, replay, resume, sources
from bench.external import run as external
from bench.external.section import BEGIN


def _no_docker(*_: object) -> None:
    msg = "docker is not installed"
    raise NotRunError(msg)


def test_main_writes_the_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, marking = build(tmp_path)
    doc = tmp_path / "benchmark.md"
    doc.write_text("# Leakage benchmark\n\n## Tools\n", encoding="utf-8")
    monkeypatch.setattr(inputs, "load", lambda: ({"spider": path}, QUESTIONS, RECORDS))
    monkeypatch.setattr(sources, "member", lambda _archive, _name: path)
    monkeypatch.setattr(external, "load_all", lambda: [marking])
    monkeypatch.setattr(external, "DOC", doc)
    monkeypatch.setattr(replay, "STORE", tmp_path / "replay.sqlite")
    monkeypatch.setattr(resume, "FILE", tmp_path / "checkpoint.pickle")
    monkeypatch.setattr("bench.adapters.launch.tool", _no_docker)
    code = external.main(
        ["--markdown", "--workdir", str(tmp_path / "work"), "--progress", str(tmp_path / "p.md")]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    main_table = out.split("\n\n")[0]  # the table by level follows
    rows = {r.split("|")[1].strip(): r for r in main_table.splitlines() if r.startswith("| ")}
    assert "100.0% (1/1)" in rows["raw"].split("|")[2]
    assert "0.0% (0/1)" in rows["incognito-sql (labels, strict)"].split("|")[2]
    assert "0.0% (0/3)" in rows["incognito-sql (web, permissive)"].split("|")[3]
    assert "docker is not installed" in rows["safedb-mcp"]
    text = doc.read_text(encoding="utf-8")
    assert text.index(BEGIN) < text.index("## Tools")
    assert "**Spider dev**: 2 questions" in text
    assert "1 attack samples (DI 1)" in text
    # a cut that shows a value whole counts in L1, a value a series reads whole too
    assert (
        "| raw | none | 100.0% (1/1) +5 L2 cuts | 33.3% (1/3) | 66.7% (2/3) | 50.0% (6/12) |"
        in text
    )
    assert "| 33% (1/3) | no claim |" in text
    assert "| incognito-sql (web, strict) | L3 but existence |" in text
    assert (
        "| incognito-sql (web, permissive) | L3 but existence, order, length, prefix, contains |"
        in text
    )
    assert text.count("| holds |") == 6  # every profile in both modes keeps its claim
    assert "| Tool | L1: recovered by a series | L3: existence |" in text  # the price table
    assert "| raw | " in text.split("Price of a fact")[1]
    # with the budget lifted a measure, no claim: its values read whole fail nothing
    lifted = "incognito-sql (labels, permissive, no budget)"
    assert lifted not in main_table
    assert f"| {lifted} | value whole |" in text.split("Capacity of a channel")[1]
