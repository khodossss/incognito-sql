"""A run's tables recounted from the answers it kept: no tool started, the same tables."""

from pathlib import Path

import pytest
from external_world import QUESTIONS, RECORDS, build

from bench.adapters.base import NotRunError
from bench.adapters.incognito import IncognitoAdapter
from bench.external import inputs, replay, resume, sources
from bench.external import run as external


def _no_docker(*_: object) -> None:
    msg = "docker is not installed"
    raise NotRunError(msg)


def _no_server(*_: object, **__: object) -> None:
    msg = "a rescoring run opened the server"
    raise AssertionError(msg)


def test_a_rescore_gives_the_same_tables_without_asking_any_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, marking = build(tmp_path)
    monkeypatch.setattr(inputs, "load", lambda: ({"spider": path}, QUESTIONS, RECORDS))
    monkeypatch.setattr(sources, "member", lambda _archive, _name: path)
    monkeypatch.setattr(external, "load_all", lambda: [marking])
    monkeypatch.setattr(replay, "STORE", tmp_path / "replay.sqlite")
    monkeypatch.setattr(resume, "FILE", tmp_path / "checkpoint.pickle")
    monkeypatch.setattr("bench.adapters.launch.tool", _no_docker)
    args = ["--workdir", str(tmp_path / "work"), "--targets", "1"]
    args += ["--progress", str(tmp_path / "progress.md")]
    assert external.main(args) == 0
    first = capsys.readouterr().out
    real = IncognitoAdapter.query
    monkeypatch.setattr(IncognitoAdapter, "query", _no_server)
    assert external.main([*args, "--rescore"]) == 0
    assert capsys.readouterr().out == first
    monkeypatch.setattr(IncognitoAdapter, "query", real)
    assert external.main([*args, "--rescore", "--targets", "2"]) == 2  # a series never run
    assert "no answer" in capsys.readouterr().err
