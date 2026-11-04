"""One marked database of the independent-sets run: each work through every tool.

Every tool runs beside its twin over the decoy copy; on the base work the inference
series (L3) follow, through every tool that ran.
"""

import contextlib
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from bench.external import attacker, inputs
from bench.external.hidden import hidden_columns
from bench.external.marking import Marking
from bench.external.replay import Store
from bench.external.report import Taken
from bench.external.score import score
from bench.external.sets import Question, Record
from bench.external.tally import Tally
from bench.external.tools import open_tools, series_tools
from bench.external.twin import decoy_copy as twin_copy
from bench.external.volume import remove_volumes
from bench.external.work import Work, works

if TYPE_CHECKING:
    from bench.adapters.base import Adapter


def run_database(
    marking: Marking,
    sets: tuple[dict[str, Path], list[Question], list[Record]],
    workdir: Path,
    into: tuple[dict[str, Tally], Taken],
    series: tuple[int, Store | None],
) -> None:
    """Run one marked database: each of its works through every tool, into ``into``."""
    (archives, questions, records), (tallies, taken), (count, store) = sets, into, series
    taken.databases.setdefault(marking.source, []).append(marking.db)
    path = inputs.database(archives, marking)
    mine = [r for r in records if r.db == marking.db]
    closing = {c.text for c in marking.conditions}
    taken.rows_only += sum(r.condition in marking.rows_only for r in mine)
    taken.safe_samples += sum(r.condition in closing and not r.attack for r in mine)
    taken.conditions += len(closing)
    taken.row_conditions += sum(bool(c.rows) for c in marking.conditions)
    try:
        for i, work in enumerate(works(path, marking, questions, records)):
            _count(taken, work)
            line = f"{marking.db} #{i}: {len(work.tasks)} tasks, {len(work.attacks)} attacks"
            sys.stderr.write(line + "\n")
            hidden = hidden_columns(work.marking, work.schema)
            target = workdir / "twin" / f"{marking.db}-{i}.sqlite"
            twin = twin_copy(path, target, hidden, work.marking.rules)
            place = workdir / f"{marking.db}-{i}"
            _through_tools(work, (twin, place), tallies, 0 if i else count, store)
            with contextlib.suppress(OSError):  # a copy per work: large sets add up
                twin.unlink()
    finally:
        remove_volumes()  # one database's copy at a time


def _count(taken: Taken, work: Work) -> None:
    for task in work.tasks:
        taken.tasks[task.source] += 1
    taken.left_out.update(work.left_out)
    for attack in work.attacks:
        taken.attacks[attack.label] += 1


def _through_tools(
    work: Work,
    files: tuple[Path, Path],
    tallies: dict[str, Tally],
    count: int,
    store: Store | None,
) -> None:
    """Run the work through every tool, each beside its twin; then the series, if any."""
    twin, place = files
    adapters, skipped = open_tools(work, place, store)
    controls: list[Adapter] = []
    try:
        controls, missing = open_tools(replace(work, path=twin), place / "twin", store, "twin")
        twins = {c.info.name: c for c in controls}
        for info, reason in {i.name: (i, r) for i, r in [*missing, *skipped]}.values():
            tallies.setdefault(info.name, Tally(info)).skipped[reason] += 1
        for adapter in (a for a in adapters if a.info.name in twins):
            tally = tallies.setdefault(adapter.info.name, Tally(adapter.info))
            score((adapter, twins[adapter.info.name]), work, tally)
        if count:
            series = series_tools(work, adapters, place / "series", store)
            controls += [a for a in series if a.info.strict]
            attacker.attack(work, series, tallies, count)
    finally:
        for adapter in [*adapters, *controls]:
            adapter.close()
