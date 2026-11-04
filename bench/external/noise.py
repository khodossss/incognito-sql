"""Noise of the L2 and L3 thresholds: raw SQL on the file and on its decoy copy.

``python -m bench.external.noise --dbs <db> ...`` sends every query of each work through
raw SQL and through raw SQL over the decoy copy, and runs the inference series on both.
On the file, a value shown in part but not whole is a piece another value or text
shares; on the decoy copy no hidden value is left, so anything found is noise. The series
on the file is the positive control (every fact should be inferred); on the decoy copy,
truth from the file, a fact inferred is noise.
"""

import argparse
import sqlite3
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from bench.dbms import Database
from bench.external import dbfile, inputs
from bench.external.asking import ask_of
from bench.external.hidden import hidden_columns
from bench.external.marking import load_all
from bench.external.targets import SqliteTruth, targets
from bench.external.tools import CappedRaw
from bench.external.twin import decoy_copy
from bench.external.work import Work, works
from incognito_sql.levels.asker import Asker
from incognito_sql.levels.infer import CHANNELS, Inference
from incognito_sql.levels.partial import Visible, shown_in_part
from incognito_sql.levels.series import run_series


def _parts(work: Work, raw: CappedRaw, twin: CappedRaw, counts: Counter[str]) -> None:
    fragments, visible = work.parts
    queries = [t.sql for t in work.tasks] + [q for a in work.attacks for q in a.queries]
    for sql in queries:
        counts["queries"] += 1
        for side, adapter in (("raw", raw), ("twin", twin)):
            text = adapter.query(sql).text
            runs = fragments.found(text)
            whole = work.oracle.found(text)
            counts[f"{side} runs"] += bool(runs)
            counts[f"{side} L2 unfiltered"] += bool(shown_in_part(runs, whole, ()))
            counts[f"{side} L2"] += bool(shown_in_part(runs, whole, (Visible([sql]), visible)))


def _series(
    con: sqlite3.Connection, work: Work, adapters: dict[str, CappedRaw], count: int
) -> dict[str, Inference]:
    out = {side: Inference() for side in adapters}
    askers = {side: Asker(ask_of(adapter)) for side, adapter in adapters.items()}
    for target in targets(con, work.marking, count):
        for side, asker in askers.items():
            for channel in CHANNELS:
                out[side].add(run_series(asker, SqliteTruth(con), target, channel))
    for inference in out.values():
        inference.settle()
    return out


def _db(path: Path) -> Database:
    return Database("sqlite", f"sqlite:///{path.as_posix()}", path=path)


def main(argv: Sequence[str] | None = None) -> int:
    """Measure and print the noise of each database."""
    parser = argparse.ArgumentParser(prog="bench.external.noise", description=__doc__)
    parser.add_argument("--dbs", nargs="*", default=None)
    parser.add_argument("--targets", type=int, default=5)
    args = parser.parse_args(argv)
    archives, questions, records = inputs.load()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        for marking in (m for m in load_all() if args.dbs is None or m.db in args.dbs):
            path = inputs.database(archives, marking)
            counts: Counter[str] = Counter()
            for i, work in enumerate(works(path, marking, questions, records)):
                hidden = hidden_columns(work.marking, work.schema)
                copy = decoy_copy(path, Path(tmp) / f"{marking.db}-{i}.sqlite", hidden)
                raw, twin = CappedRaw(_db(path)), CappedRaw(_db(copy))
                _parts(work, raw, twin, counts)
                if i == 0 and args.targets:
                    with dbfile.opened(path) as con:
                        found = _series(con, work, {"raw": raw, "twin": twin}, args.targets)
                    for side, inference in found.items():
                        shares = ", ".join(f"{c} {inference.share(c)}" for c in CHANNELS)
                        sys.stdout.write(
                            f"{marking.db} series {side}: {shares}; whole {inference.whole};"
                            f" queries {inference.spent}\n"
                        )
                raw.close()
                twin.close()
            sys.stdout.write(f"{marking.db} L2: {dict(sorted(counts.items()))}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
