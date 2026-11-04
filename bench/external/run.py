"""Run every tool on the independent sets, on SQLite; print or write the section.

``uv run poe bench-external`` downloads the sets into the bench cache (pinned digests),
opens every marked database, and runs its questions and the SecureSQL samples through
raw SQL, every competitor that reads SQLite and incognito-sql (both modes); the
inference series (L3) run on ``--targets`` values of each database through every tool
that ran. ``--markdown`` writes the section into ``docs/benchmark.md``. The exit code
is 1 when incognito-sql shows a hidden value or a series reads one whole.

``--rescore`` recounts the tables from the answers an earlier run kept, starting no tool:
after a change of the oracle or the report, not of the server or of a tool.
"""

import argparse
import contextlib
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from bench.awake import awake
from bench.external import inputs, sources
from bench.external.claims import ours_broken
from bench.external.database import run_database
from bench.external.levels import capacity, levels, prices
from bench.external.marking import Marking, load_all
from bench.external.replay import Store, UnrecordedError
from bench.external.report import Taken, fills, table
from bench.external.resume import PROGRESS, Checkpoint, OverLimitError, key, show, watchdog
from bench.external.section import block, fill, splice
from bench.external.tally import Tally
from bench.run import DOC

TEMPLATE = Path(__file__).parents[1] / "benchmark.md.in"
TARGETS = 3  # targets of the inference series per database
DB_LIMIT_S = 90 * 60.0  # one database over this stops the run: a stall shows, not hours


def run(  # noqa: PLR0913 -- the run, its store, its checkpoint, limit and progress
    markings: Sequence[Marking],
    workdir: Path,
    count: int = 0,
    store: Store | None = None,
    *,
    checkpoint: Checkpoint | None = None,
    limit_s: float = DB_LIMIT_S,
    progress: Path | None = None,
) -> tuple[list[Tally], Taken]:
    """Run every marked database; return one tally per tool and what was taken.

    The inference series run on ``count`` targets of each database's base work; with a
    ``store``, competitors are replayed from it (``bench.external.replay``). With a
    ``checkpoint``, the databases it holds are not run again and each finished one is
    added to it; a database over ``limit_s`` stops the run (``bench.external.resume``).
    """
    sets = inputs.load()
    done, tallies, taken = checkpoint.resumed() if checkpoint else ([], {}, Taken())
    for marking in markings:
        if marking.db in done:
            sys.stderr.write(f"{marking.db}: from the checkpoint\n")
            continue
        with watchdog(marking.db, limit_s):
            run_database(marking, sets, workdir, (tallies, taken), (count, store))
        done.append(marking.db)
        if checkpoint is not None:
            checkpoint.save(done, tallies, taken)
        if progress is not None:
            show(progress, done, len(markings), tallies)
    for tally in tallies.values():
        tally.inference.settle()
    return list(tallies.values()), taken


def main(argv: Sequence[str] | None = None) -> int:
    """Run, print the table, and write the section with ``--markdown``."""
    parser = argparse.ArgumentParser(prog="bench.external.run", description=__doc__)
    parser.add_argument("--markdown", action="store_true", help=f"write the section of {DOC}")
    parser.add_argument("--dbs", nargs="*", default=None, help="databases to run")
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument("--targets", type=int, default=TARGETS, help="L3 targets per database")
    parser.add_argument("--fresh", action="store_true", help="ask every tool anew, no replay")
    parser.add_argument("--rescore", action="store_true", help="recount from kept answers only")
    parser.add_argument("--restart", action="store_true", help="ignore the checkpoint")
    parser.add_argument("--db-limit", type=float, default=DB_LIMIT_S / 60, help="minutes")
    parser.add_argument("--progress", type=Path, default=PROGRESS, help="tables so far")
    args = parser.parse_args(argv)
    markings = [m for m in load_all() if args.dbs is None or m.db in args.dbs]
    with contextlib.ExitStack() as stack:
        workdir = args.workdir or Path(
            stack.enter_context(
                tempfile.TemporaryDirectory(prefix="incognito-ext-", ignore_cleanup_errors=True)
            )
        )
        store = Store(fresh=args.fresh, rescore=args.rescore)
        stack.callback(store.close)
        run_key = key([*sorted(m.db for m in markings), str(args.targets), str(args.rescore)])
        checkpoint = Checkpoint(run_key, fresh=args.fresh or args.restart or args.rescore)
        try:
            tallies, taken = run(
                markings,
                workdir,
                args.targets,
                store,
                checkpoint=checkpoint,
                limit_s=args.db_limit * 60,
                progress=args.progress,
            )
        except OverLimitError as exc:
            sys.stderr.write(f"stopped: {exc}; run again to resume\n")
            return 2
        except UnrecordedError as exc:
            sys.stderr.write(f"stopped: {exc}\n")
            return 2
    section = block(TEMPLATE.read_text(encoding="utf-8"))
    if args.markdown and section is not None:
        filled = fill(
            section, fills(tallies, taken, (sources.SPIDER, sources.BIRD, sources.SECURESQL))
        )
        previous = DOC.read_text(encoding="utf-8")
        DOC.write_text(splice(previous, filled), encoding="utf-8", newline="\n")
    sys.stdout.write(
        "\n\n".join((table(tallies), levels(tallies), prices(tallies), capacity(tallies))) + "\n"
    )
    return 1 if any(map(ours_broken, tallies)) else 0


if __name__ == "__main__":
    with awake():
        raise SystemExit(main())
