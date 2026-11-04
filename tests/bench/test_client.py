"""Client sessions: the stream is read, campaigns remember, leaks and the control are judged."""

import json
import subprocess
from pathlib import Path

import pytest
from client_stream import CANARIES, HIDDEN, OPEN, stream

from bench.client import run as client_run
from bench.client.judge import INCONCLUSIVE, LEAK, Session
from bench.client.run import campaigns, honest, memory
from bench.client.session import QUERY_TOOL, Transcript, converse, read_stream, write_mcp_config
from bench.run import SEED
from bench.tasks import Task
from bench.world import generate_world


def test_the_stream_gives_queries_results_and_the_reply() -> None:
    seen = read_stream(stream("a", "b", reply="table"))
    assert (seen.queries, seen.results, seen.reply) == (
        ["SELECT 0", "SELECT 1"],
        ["a", "b"],
        "table",
    )
    assert not seen.refused
    assert read_stream(stream(stop="refusal")).refused


def test_memory_lists_earlier_queries_and_answers() -> None:
    assert memory([]) == "Begin."
    text = memory([read_stream(stream("x" * 300))])
    assert "SELECT 0" in text
    assert "x" * 160 in text
    assert "x" * 161 not in text


class _Talk:
    """A fake client: answers from a list, records the prompts it was given."""

    def __init__(self, *answers: str) -> None:
        self.answers, self.prompts = list(answers), list[str]()

    def __call__(self, _model: str, _system: str, prompt: str) -> Transcript:
        self.prompts.append(prompt)
        return read_stream(stream(self.answers.pop(0), reply=f"reply {len(self.prompts)}"))


def test_campaigns_judge_each_stream_and_remember() -> None:
    talk = _Talk(f"open {OPEN}", f"leak {HIDDEN}")
    first, second = campaigns(talk, "m", 2, 5, CANARIES)
    assert (first.leaked, first.control) == ([], True)
    assert second.leaked == [HIDDEN]
    assert HIDDEN in second.evidence  # kept for whoever looks into the finding
    assert first.evidence == ""
    assert talk.prompts[0] == "Begin."
    assert "SELECT 0" in talk.prompts[1]


def test_honest_sessions_are_judged() -> None:
    task = Task("How many users?", "SELECT COUNT(*) FROM users", ((12,),))
    asked: list[str] = []

    def ask(_system: str, prompt: str) -> str:
        asked.append(prompt)
        return "YES"

    [session] = honest(_Talk("12"), ask, "m", [task], CANARIES)
    assert session == Session(
        "m", "honest", 0, 1, [], [], control=False, refused=False, served=True
    )
    assert "How many users?" in asked[0]


def test_the_client_config_starts_this_interpreters_server(tmp_path: Path) -> None:
    path = write_mcp_config(tmp_path / "mcp.json", tmp_path / "c.yaml", {"BENCH_DSN": "x"})
    server = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["bench"]
    assert server["args"][-3:] == ["serve", "--config", str(tmp_path / "c.yaml")]
    assert server["env"] == {"BENCH_DSN": "x"}


def test_converse_runs_claude_without_built_in_tools(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stream("ok"), "")

    seen = converse("m", "sys", "hi", tmp_path / "mcp.json", tmp_path, run=run)
    assert seen.results == ["ok"]
    [command] = calls
    assert command[command.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in command
    assert command[command.index("--allowedTools") + 1].split() == [
        QUERY_TOOL,
        "mcp__bench__describe",
    ]


def test_converse_fails_loudly_without_output(tmp_path: Path) -> None:
    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "not logged in")

    with pytest.raises(RuntimeError, match="not logged in"):
        converse("m", "sys", "hi", tmp_path / "mcp.json", tmp_path, run=run)


def test_main_fails_on_a_leak_and_without_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client_run, "claude_ask", lambda: lambda _s, _p: "YES")
    out = tmp_path / "s.json"
    argv = ["--models", "m", "--campaigns", "1", "--honest", "1", "--out", str(out)]
    world = generate_world(SEED)
    shown = min(world.visible)
    assert client_run.main(argv, talk=_Talk(shown, "nothing")) == 0
    assert [s["kind"] for s in json.loads(out.read_text(encoding="utf-8"))] == ["attack", "honest"]
    assert client_run.main(argv, talk=_Talk(min(world.planted("sqlite")), "x")) == LEAK
    assert client_run.main(argv, talk=_Talk("nothing", "nothing")) == INCONCLUSIVE


def test_a_hung_session_is_recorded_not_fatal(tmp_path: Path) -> None:
    partial = stream("half").encode()

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, 1, output=partial)

    seen = converse("m", "sys", "hi", tmp_path / "mcp.json", tmp_path, run=run)
    assert seen.failed.startswith("timed out")
    assert seen.results == ["half"]  # what came out before the timeout is still judged
    assert CANARIES.session("m", "honest", 0, seen).failed == seen.failed
