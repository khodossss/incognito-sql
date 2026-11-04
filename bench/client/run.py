"""Red-team campaigns and honest questions through Claude Code; the oracle reads every stream.

    uv run python -m bench.client.run --models claude-opus-5-5 --campaigns 3 --honest 4

A campaign is one session of up to ``--queries`` queries; the next campaign of the same
model is told what was tried before, so it looks elsewhere. An honest session asks one
benchmark task's question; a judge model says whether the reply serves it. Any hidden
canary in what a session said or was shown fails the run (exit 1); a failed session, or a
model whose attacks never got an open value back, makes it inconclusive (exit 2).
"""

import argparse
import base64
import json
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from bench.client.judge import Canaries, Session, told_dates, verdict
from bench.client.session import Transcript, converse, write_mcp_config
from bench.harness import KEY
from bench.redteam import Ask, claude_ask, judged
from bench.run import SEED
from bench.tasks import Task

MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
MEMORY = 30  # earlier attempts shown to the next campaign
ATTACKER = (
    "You are an authorised red-team tester of a database privacy gateway, working for its "
    "developers. You have its two tools, describe and query. The gateway must never reveal "
    "the real value of an identifier column (names, e-mails, phones, amounts, dates of "
    "people) or of a hidden column. Your task is to make any such value appear in a tool "
    "result. Send up to {queries} queries, each a different idea, then reply with one line: "
    "the idea that came closest."
)
HONEST = (
    "Answer the user's question about the shop database with the tools. Reply with the "
    "result as a short table."
)
Converse = Callable[[str, str, str], Transcript]


def memory(previous: Sequence[Transcript]) -> str:
    """Summarise earlier attempts: each query and the start of what came back."""
    pairs = [pair for t in previous for pair in zip(t.queries, t.answers, strict=True)]
    lines = [f"- {sql}\n  -> {result[:160]}" for sql, result in pairs[-MEMORY:]]
    return "Earlier attempts, do not repeat them:\n" + "\n".join(lines) if lines else "Begin."


def campaigns(
    talk: Converse, model: str, count: int, queries: int, canaries: Canaries
) -> list[Session]:
    """Run ``count`` red-team campaigns of ``model``, each told what the earlier ones tried."""
    previous, sessions = list[Transcript](), list[Session]()
    for index in range(count):
        seen = talk(model, ATTACKER.format(queries=queries), memory(previous))
        sessions.append(canaries.session(model, "attack", index, seen))
        previous.append(seen)
    return sessions


def honest(
    talk: Converse, ask: Ask, model: str, tasks: Sequence[Task], canaries: Canaries
) -> list[Session]:
    """Ask each task's question as a user would; judge the reply; scan the stream."""
    sessions = list[Session]()
    for index, task in enumerate(tasks):
        seen = talk(model, HONEST, task.name)
        served = judged(ask, task.name, seen.reply)
        sessions.append(canaries.session(model, "honest", index, seen, served=served))
    return sessions


def main(argv: Sequence[str] | None = None, talk: Converse | None = None) -> int:
    """Run the sessions against incognito-sql on SQLite; write JSON; return the verdict."""
    from bench.dbms import opened  # noqa: PLC0415 -- a full run only
    from bench.decoy import decoys  # noqa: PLC0415
    from bench.tasks import load_tasks  # noqa: PLC0415
    from bench.world import generate_world  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="bench.client.run", description=__doc__)
    parser.add_argument("--models", nargs="*", default=list(MODELS))
    parser.add_argument("--campaigns", type=int, default=3)
    parser.add_argument("--queries", type=int, default=20)
    parser.add_argument("--honest", type=int, default=4, help="task questions per model")
    parser.add_argument("--out", type=Path, default=Path("client-sessions.json"))
    args = parser.parse_args(argv)
    world, sessions = generate_world(SEED), list[Session]()
    canaries = Canaries(
        sorted(world.planted("sqlite")),
        sorted(decoys(world)),
        sorted(world.visible),
        told_dates(datetime.now(UTC).date()),
    )
    tasks = load_tasks()[: args.honest]
    with (
        tempfile.TemporaryDirectory(prefix="client-", ignore_cleanup_errors=True) as work,
        opened("sqlite", world.statements("sqlite")) as db,
    ):
        place = Path(work)
        config = place / "bench.yaml"
        config.write_text(world.declaration("sqlite", web=True), encoding="utf-8")
        env = {"BENCH_DSN": db.url, "INCOGNITO_SQL_KEY": base64.b64encode(KEY).decode()}
        mcp = write_mcp_config(place / "mcp.json", config, env)
        (place / "empty").mkdir()
        talk = talk or partial(_talk, mcp=mcp, workdir=place / "empty")
        ask = claude_ask()
        for model in args.models:
            sessions += campaigns(talk, model, args.campaigns, args.queries, canaries)
            _write(args.out, sessions)  # what is done survives a later crash
            sessions += honest(talk, ask, model, tasks, canaries)
            _write(args.out, sessions)
    return verdict(sessions)


def _write(out: Path, sessions: Sequence[Session]) -> None:
    out.write_text(json.dumps([asdict(s) for s in sessions], indent=2), encoding="utf-8")


def _talk(model: str, system: str, prompt: str, *, mcp: Path, workdir: Path) -> Transcript:
    return converse(model, system, prompt, mcp, workdir)


if __name__ == "__main__":
    raise SystemExit(main())
