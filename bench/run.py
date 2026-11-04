"""Run the leakage benchmark: ``run`` scores opened adapters; ``main`` is the full run.

``uv run poe bench`` builds the world on every DBMS, opens incognito-sql (both output
modes), raw SQL and each competitor where it supports that DBMS, and prints the report;
``--markdown`` writes ``docs/benchmark.md`` from it.
"""

import argparse
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from bench.adapters.base import Adapter
from bench.awake import awake
from bench.cases import Case, load_cases
from bench.decoy import decoys
from bench.profiles import claim_of
from bench.report import Report
from bench.schema import DIALECTS
from bench.score import Row, score
from bench.tasks import Task, load_tasks
from bench.world import World, generate_world

SEED = 15  # the world of the corpus tests and the hand-labelled tasks
DOC = Path(__file__).parent.parent / "docs" / "benchmark.md"


def run(
    adapters: Iterable[Adapter], corpus: Sequence[Case], tasks: Sequence[Task], world: World
) -> Report:
    """Score every adapter on the corpus and the tasks; the report holds one row each."""
    report, hidden = Report(), (world.forbidden, decoys(world))
    report.add([score(a, corpus, tasks, hidden) for a in adapters])
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """Run every adapter on every DBMS asked for; print or write the report.

    The exit code is 1 when incognito-sql shows any hidden canary or any decoy.
    """
    from bench import matrix  # noqa: PLC0415 -- containers and competitors only for a full run
    from bench.doc import render  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="bench.run", description=__doc__)
    parser.add_argument("--dialects", nargs="*", default=list(DIALECTS))
    parser.add_argument("--only", nargs="*", default=None, help="tool names to run")
    parser.add_argument("--markdown", action="store_true", help=f"write {DOC}")
    parser.add_argument("--workdir", type=Path, default=None)
    args = parser.parse_args(argv)
    world = generate_world(SEED)
    report, meta = matrix.run_all(
        world, load_cases(), load_tasks(), args.dialects, args.only, args.workdir
    )
    if args.markdown:
        previous = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        DOC.write_text(render(report, meta, previous), encoding="utf-8", newline="\n")
    sys.stdout.write(report.markdown() + "\n")
    failed = [r for r in report.rows if r.info.strict and breaks_claim(r)]
    return 1 if failed else 0


def breaks_claim(row: Row) -> bool:
    """Tell whether a row of ours shows more than its profile claims to hold.

    A profile claiming L1 only breaks on an attack showing a hidden value whole; any other
    on any attack hit. An honest answer carrying a hidden value breaks every profile: the
    row does not count whole values there apart.
    """
    if claim_of(row.info).level == "L1":
        return row.listing_leak or bool(row.whole or row.exposed)
    return bool(row.leaked or row.noise or row.exposed)


if __name__ == "__main__":
    with awake():
        raise SystemExit(main())
