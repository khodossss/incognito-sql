"""Competitors' answers kept on disk: stored as they run, replayed without the tool."""

from importlib import metadata
from pathlib import Path

import pytest
from external_world import QUESTIONS, RECORDS, build

from bench.adapters.base import ANSWERED, ERROR, Adapter, NotRunError, Outcome
from bench.adapters.raw import INFO
from bench.external import replay
from bench.external.work import works


class Counting:
    """A tool that answers every query with its text and counts what it was asked."""

    info = INFO

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.closed = False

    def query(self, sql: str) -> Outcome:
        self.asked.append(sql)
        return Outcome(ANSWERED, sql.upper(), 1.0, [[1]])

    def channels(self) -> dict[str, str]:
        return {"stderr": f"after {len(self.asked)}"}

    def static(self) -> str:
        return "listing"

    def close(self) -> None:
        self.closed = True


def test_answers_are_replayed_without_starting_the_tool(tmp_path: Path) -> None:
    store = replay.Store(tmp_path / "r.sqlite")
    tool = Counting()
    first = replay.opened(INFO, lambda: tool, store, "k")  # type: ignore[arg-type,return-value]
    assert first.static() == "listing"
    assert first.query("select 1").text == "SELECT 1"
    assert first.channels() == {"stderr": "after 1"}
    assert first.channels() == {}
    first.close()
    assert tool.closed

    def never() -> Counting:
        raise AssertionError

    again = replay.opened(INFO, never, store, "k")  # type: ignore[arg-type]
    assert again.static() == "listing"
    out = again.query("select 1")
    assert (out.status, out.rows) == (ANSWERED, [[1]])
    assert again.channels() == {"stderr": "after 1"}
    again.close()
    fresh = replay.Store(tmp_path / "r.sqlite", fresh=True)
    assert fresh.get("k", "static", "") is None
    fresh.close()
    store.close()


def test_a_query_not_seen_starts_the_tool_once(tmp_path: Path) -> None:
    store = replay.Store(tmp_path / "r.sqlite")
    store.put("k", "static", "", "listing")
    tool = Counting()
    starts: list[int] = []

    def start() -> Counting:
        starts.append(1)
        return tool

    lazy = replay.opened(INFO, start, store, "k")  # type: ignore[arg-type]
    lazy.query("a")
    lazy.query("b")
    assert (starts, tool.asked) == ([1], ["a", "b"])

    def broken() -> Counting:
        msg = "docker is not running"
        raise NotRunError(msg)

    out = replay.Replayed(INFO, broken, store, "other").query("a")  # type: ignore[arg-type]
    assert out.status == ERROR
    assert "docker is not running" in out.text
    with pytest.raises(NotRunError):
        replay.opened(INFO, broken, store, "third")  # type: ignore[arg-type]
    store.close()


def test_the_key_follows_the_tool_the_side_and_the_work(tmp_path: Path) -> None:
    path, marking = build(tmp_path)
    base, condition = list(works(path, marking, QUESTIONS, RECORDS))[:2]
    keys = {
        replay.key(INFO, "tool", base),
        replay.key(INFO, "twin", base),
        replay.key(INFO, "tool", condition),
        replay.key(INFO.__class__(**{**INFO.__dict__, "version": "2"}), "tool", base),
    }
    assert len(keys) == 4
    assert replay.key(INFO, "tool", base) == replay.key(INFO, "tool", base)


def test_a_rescoring_store_reads_back_and_never_starts_the_tool(tmp_path: Path) -> None:
    store = replay.Store(tmp_path / "r.sqlite")
    tool: Adapter = Counting()  # type: ignore[assignment]
    replay.Replayed(INFO, lambda: tool, store, "k", tool=tool).query("a")
    store.close()
    rescore = replay.Store(tmp_path / "r.sqlite", rescore=True)
    kept = replay.Replayed(INFO, lambda: tool, rescore, "k", tool=tool)
    assert kept.query("a").text == "A"
    with pytest.raises(replay.UnrecordedError, match="no answer"):
        kept.query("b")  # a query the kept run never asked
    kept.close()
    rescore.close()
    assert isinstance(tool, Counting)
    assert tool.asked == ["a"]
    assert tool.closed  # an open tool is closed with its replay


def test_the_server_digest_follows_its_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    before = replay.server_code.__wrapped__(tmp_path)
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert replay.server_code.__wrapped__(tmp_path) != before
    assert len(replay.server_code()) == 64  # the package's own sources


def test_a_rescore_starts_no_competitor_and_keeps_why_one_did_not_run(tmp_path: Path) -> None:
    def no_docker() -> Adapter:
        msg = "docker is not installed"
        raise NotRunError(msg)

    def never() -> Adapter:
        msg = "a rescore started a tool"
        raise AssertionError(msg)

    store = replay.Store(tmp_path / "r.sqlite")
    with pytest.raises(NotRunError):
        replay.opened(INFO, no_docker, store, "k")
    store.close()
    rescore = replay.Store(tmp_path / "r.sqlite", rescore=True)
    with pytest.raises(NotRunError, match="docker is not installed"):
        replay.opened(INFO, never, rescore, "k")
    with pytest.raises(NotRunError, match="no answers kept"):
        replay.opened(INFO, never, rescore, "other")
    rescore.close()


class _Dist:
    def __init__(self, name: str, version: str) -> None:
        self.metadata, self.version = {"Name": name}, version


def test_another_version_of_a_dependency_is_another_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def digest(sqlglot: str) -> str:
        dists = [_Dist("sqlglot", sqlglot), _Dist("SQLAlchemy", "2.0.40")]
        monkeypatch.setattr(metadata, "distributions", lambda: dists)
        return replay.installed.__wrapped__()

    assert digest("30.25.0") == digest("30.25.0") != digest("30.26.0")
