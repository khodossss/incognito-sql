"""LLM red team and LLM-judged utility, for the scheduled benchmark only (``bench.yml``).

The model is injected as ``Ask``: (system, prompt) -> reply text, so the loop is tested
with a fake. The red team sees the schema the tool describes, sends one SQL query per
round, reads the answer, and tries again; the oracle judges every round. The judge reads
a task's question and a tool's answer and says whether the answer serves the question.
``main`` runs both against incognito-sql on SQLite with Claude through the Claude Code
CLI.
"""

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from bench.adapters.base import Adapter
from bench.oracle import leaks

Ask = Callable[[str, str], str]
MODEL = "claude-opus-5-5"  # answered by Claude Code CLI 2.1.314
ATTACKER = (
    "You are an authorised red-team tester of a database privacy gateway. The gateway "
    "answers SQL but must never reveal values of hidden or identifier columns. Find a "
    "query that makes any such value appear in its answer or its error. Reply with one "
    "SQL query and nothing else."
)
JUDGE = (
    "You grade whether a database answer serves a question. Pseudonyms or links in place "
    "of personal values are fine. Reply YES or NO."
)
_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class Attempt:
    """One red-team round: the query sent, the outcome, the canaries found."""

    round: int
    sql: str
    status: str
    leaked: list[str]


def sql_of(reply: str) -> str:
    """Return the SQL in a model reply, fenced or bare."""
    found = _FENCE.search(reply)
    return (found.group(1) if found else reply).strip().rstrip(";")


def red_team(
    ask: Ask, adapter: Adapter, schema: str, forbidden: Iterable[str], rounds: int = 10
) -> list[Attempt]:
    """Let the model attack ``adapter`` for ``rounds`` queries; judge each with the oracle."""
    hidden, history, attempts = list(forbidden), list[str](), list[Attempt]()
    for i in range(rounds):
        prompt = f"Schema:\n{schema}\n\nEarlier rounds:\n" + "\n".join(history[-6:])
        sql = sql_of(ask(ATTACKER, prompt))
        out = adapter.query(sql)
        text = "\n".join([out.text, *adapter.channels().values()])
        attempts.append(Attempt(i + 1, sql, out.status, leaks(text, hidden)))
        history.append(f"SQL: {sql}\nAnswer: {out.text[:800]}")
    return attempts


def judged(ask: Ask, question: str, answer: str) -> bool:
    """Ask the judge whether ``answer`` serves ``question``."""
    reply = ask(JUDGE, f"Question: {question}\nAnswer: {answer[:4000]}")
    return reply.strip().upper().startswith("YES")


Run = Callable[..., "subprocess.CompletedProcess[str]"]


def claude_ask(model: str = MODEL, run: Run = subprocess.run) -> Ask:
    """Return an ``Ask`` backed by the Claude Code CLI on a subscription.

    The CLI uses the signed-in subscription of the machine it runs on. Each
    question is a fresh print-mode session without tools, settings, hooks or MCP servers,
    started in an empty directory.
    """
    command = [
        shutil.which("claude") or "claude",
        "-p",
        "--model",
        model,
        "--tools",
        "",
        "--safe-mode",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--system-prompt",
    ]

    def ask(system: str, prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="redteam-ask-") as empty:
            done = run(
                [*command, system],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=empty,
                check=False,
                timeout=600,
            )
        reply: dict[str, Any] = json.loads(done.stdout or "{}")
        if done.returncode or reply.get("is_error") or "result" not in reply:
            msg = f"claude -p failed ({done.returncode}): {done.stderr.strip()[:300]}"
            raise RuntimeError(msg)
        return "" if reply.get("stop_reason") == "refusal" else str(reply["result"])

    return ask


def main(argv: Sequence[str] | None = None, ask: Ask | None = None) -> int:
    """Red-team and judge incognito-sql on SQLite; write JSON; fail on any leak."""
    from bench.adapters.incognito import open_incognito  # noqa: PLC0415 -- a full run only
    from bench.dbms import opened  # noqa: PLC0415
    from bench.run import SEED  # noqa: PLC0415
    from bench.tasks import load_tasks  # noqa: PLC0415
    from bench.world import generate_world  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="bench.redteam", description=__doc__)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--out", type=Path, default=Path("redteam.json"))
    args = parser.parse_args(argv)
    ask = ask or claude_ask()
    world, result = generate_world(SEED), dict[str, object]()
    with (
        tempfile.TemporaryDirectory(prefix="redteam-", ignore_cleanup_errors=True) as work,
        opened("sqlite", world.statements("sqlite")) as db,
    ):
        adapters = open_incognito(world, db, Path(work))
        try:
            for adapter in adapters:
                schema = json.loads(adapter.static())[0]
                attempts = red_team(ask, adapter, json.dumps(schema), world.forbidden, args.rounds)
                served = [judged(ask, t.name, adapter.query(t.sql).text) for t in load_tasks()]
                result[adapter.info.name] = {
                    "attempts": [asdict(a) for a in attempts],
                    "judged_utility": sum(served) / len(served),
                }
        finally:
            for adapter in adapters:
                adapter.close()
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    leaked = any(a["leaked"] for r in result.values() for a in r["attempts"])  # type: ignore[index]
    return 1 if leaked else 0


if __name__ == "__main__":
    raise SystemExit(main())
