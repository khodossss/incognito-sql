"""A long run survives a stop: finished databases are kept, a stalled one shows quickly."""

import pickle
import time
from pathlib import Path, PurePath

import pytest
from external_world import QUESTIONS, RECORDS, build

from bench.adapters.base import NotRunError
from bench.adapters.raw import INFO
from bench.external import inputs, replay, resume, sources
from bench.external import run as external
from bench.external.report import Taken
from bench.external.resume import Checkpoint, OverLimitError, watchdog
from bench.external.tally import Tally


def test_a_checkpoint_resumes_only_its_own_run(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.pickle"
    taken = Taken()
    taken.conditions = 3
    Checkpoint("run-a", path).save(["shop"], {"raw": Tally(INFO)}, taken)
    done, tallies, again = Checkpoint("run-a", path).resumed()
    assert (done, list(tallies), again.conditions) == (["shop"], ["raw"], 3)
    assert Checkpoint("run-b", path).resumed()[0] == []  # code or arguments changed
    assert Checkpoint("run-a", path, fresh=True).resumed()[0] == []
    path.write_bytes(b"not a checkpoint")
    assert Checkpoint("run-a", path).resumed()[0] == []
    # Written by an older release, it names a module or class that is gone.
    old = pickle.dumps(("run-a", ([], {}, PurePath("x"))))
    path.write_bytes(old.replace(b"pathlib", b"gone_lb"))
    assert Checkpoint("run-a", path).resumed()[0] == []


def test_the_key_follows_the_arguments() -> None:
    assert resume.key(["shop", "3"]) == resume.key(["shop", "3"]) != resume.key(["shop", "4"])


def _stall(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.01)


def test_a_database_over_its_limit_stops_the_run(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(OverLimitError, match="slow ran over"), watchdog("slow", 0.2, 0.05):
        _stall(5)
    assert "still on slow" in capsys.readouterr().err
    with watchdog("quick", 5, 0.05):
        pass


def _no_docker(*_: object) -> None:
    msg = "docker is not installed"
    raise NotRunError(msg)


def test_a_second_run_takes_finished_databases_from_the_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, marking = build(tmp_path)
    monkeypatch.setattr(inputs, "load", lambda: ({"spider": path}, QUESTIONS, RECORDS))
    monkeypatch.setattr(sources, "member", lambda _archive, _name: path)
    monkeypatch.setattr(external, "load_all", lambda: [marking])
    monkeypatch.setattr(replay, "STORE", tmp_path / "replay.sqlite")
    monkeypatch.setattr(resume, "FILE", tmp_path / "checkpoint.pickle")
    monkeypatch.setattr("bench.adapters.launch.tool", _no_docker)
    progress = tmp_path / "progress.md"
    args = ["--workdir", str(tmp_path / "work"), "--targets", "0", "--progress", str(progress)]
    assert external.main(args) == 0
    first = capsys.readouterr()
    shown = progress.read_text(encoding="utf-8")
    assert shown.startswith("After 1 of 1 databases")
    assert "| raw |" in shown
    assert "| Tool | Claimed |" in shown  # the table by level too
    assert "| Tool | L1: recovered by a series |" in shown  # and the price table
    assert external.main(args) == 0
    second = capsys.readouterr()
    assert "shop: from the checkpoint" in second.err
    assert "shop #0" not in second.err
    assert second.out == first.out  # the same table, read back
    assert external.main([*args, "--restart"]) == 0
    assert "shop #0" in capsys.readouterr().err
