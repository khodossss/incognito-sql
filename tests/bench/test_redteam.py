"""The LLM red team and judge with a fake model: the loop, the oracle, the verdicts."""

import json
import subprocess
from pathlib import Path

import pytest

from bench import redteam
from bench.adapters.base import ANSWERED, Outcome
from bench.tasks import Task
from bench.world import World


class Echo:
    """A tool that answers every query with the canary it was asked about."""

    def __init__(self, secret: str) -> None:
        self.secret, self.sent = secret, list[str]()

    def query(self, sql: str) -> Outcome:
        self.sent.append(sql)
        return Outcome(ANSWERED, self.secret if "leak" in sql else "[]", 1.0)

    def channels(self) -> dict[str, str]:
        return {}


def test_sql_is_taken_from_a_fenced_or_bare_reply() -> None:
    assert redteam.sql_of("Try:\n```sql\nSELECT 1;\n```") == "SELECT 1"
    assert redteam.sql_of(" SELECT 2 ") == "SELECT 2"


def test_rounds_are_judged_by_the_oracle_and_see_earlier_answers() -> None:
    prompts: list[str] = []
    replies = iter(["SELECT 1", "SELECT leak"])

    def ask(system: str, prompt: str) -> str:
        assert system == redteam.ATTACKER
        prompts.append(prompt)
        return next(replies)

    tool = Echo("Zq1k9v9g8j8j")
    attempts = redteam.red_team(ask, tool, "users(id)", {"Zq1k9v9g8j8j"}, rounds=2)  # type: ignore[arg-type]
    assert [a.leaked for a in attempts] == [[], ["Zq1k9v9g8j8j"]]
    assert "SQL: SELECT 1" in prompts[1]


def test_judge_reads_yes_or_no() -> None:
    assert redteam.judged(lambda _s, _p: "YES, it does", "q", "a")
    assert not redteam.judged(lambda _s, _p: "no", "q", "a")


def test_main_runs_against_incognito_and_writes_json(
    tmp_path: Path, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("bench.tasks.load_tasks", lambda: [Task("n", "SELECT 1", ((1,),))])

    def ask(system: str, _prompt: str) -> str:
        return "SELECT name FROM users" if system == redteam.ATTACKER else "YES"

    out = tmp_path / "r.json"
    assert redteam.main(["--rounds", "1", "--out", str(out)], ask) == 0
    result = json.loads(out.read_text("utf-8"))
    assert set(result) == {"incognito-sql (web)", "incognito-sql (labels)"}
    assert result["incognito-sql (web)"]["attempts"][0]["leaked"] == []
    assert world.forbidden


class FakeRun:
    """Stands in for ``subprocess.run``: records the call, returns a canned CLI reply."""

    def __init__(self, stdout: str, code: int = 0) -> None:
        self.stdout, self.code, self.calls = stdout, code, list[dict[str, object]]()

    def __call__(self, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append({"args": args, **kwargs})
        return subprocess.CompletedProcess(args, self.code, self.stdout, "boom")


def test_claude_ask_sends_a_tool_less_print_session_and_reads_the_result() -> None:
    run = FakeRun(json.dumps({"is_error": False, "stop_reason": "end_turn", "result": "SELECT 1"}))
    assert redteam.claude_ask("m", run)("sys", "the prompt") == "SELECT 1"
    call = run.calls[0]
    args = call["args"]
    assert isinstance(args, list)
    assert args[1:4] == ["-p", "--model", "m"]
    assert {"--safe-mode", "--strict-mcp-config", "--no-session-persistence"} <= set(args)
    assert args[args.index("--tools") + 1] == ""
    assert args[-2:] == ["--system-prompt", "sys"]
    assert call["input"] == "the prompt"
    assert not Path(str(call["cwd"])).exists()  # an empty directory, removed afterwards


def test_claude_ask_maps_a_refusal_to_an_empty_reply() -> None:
    run = FakeRun(json.dumps({"is_error": False, "stop_reason": "refusal", "result": "no"}))
    assert redteam.claude_ask("m", run)("s", "p") == ""


@pytest.mark.parametrize(
    ("stdout", "code"),
    [(json.dumps({"is_error": True, "result": "auth"}), 0), ("", 1), ("{}", 0)],
)
def test_claude_ask_fails_loudly_on_a_cli_error(stdout: str, code: int) -> None:
    with pytest.raises(RuntimeError, match="claude -p failed"):
        redteam.claude_ask("m", FakeRun(stdout, code))("s", "p")
