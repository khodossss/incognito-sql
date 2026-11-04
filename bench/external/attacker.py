"""Run the inference series of one work through every tool: one session per tool."""

from collections.abc import Iterable, MutableMapping

from bench.adapters.base import Adapter
from bench.external import dbfile
from bench.external.asking import ask_of
from bench.external.tally import Tally
from bench.external.targets import SqliteTruth, targets
from bench.external.work import Work
from bench.profiles import measured
from incognito_sql.levels.asker import CAPACITY_SERIES, CAPACITY_TOOL, Asker
from incognito_sql.levels.infer import CHANNELS
from incognito_sql.levels.series import run_series


def attack(
    work: Work, adapters: Iterable[Adapter], tallies: MutableMapping[str, Tally], count: int
) -> None:
    """Run every channel's series on ``count`` targets through each tool into its tally.

    A row with the literal budget lifted runs the series only: its tally starts here.
    """
    with dbfile.opened(work.path) as con:
        chosen = targets(con, work.marking, count)
        for adapter in adapters:
            lifted = measured(adapter.info)
            if lifted:
                tallies.setdefault(adapter.info.name, Tally(adapter.info))
            tally = tallies.get(adapter.info.name)
            if tally is None:
                continue
            asker = (
                Asker(ask_of(adapter), CAPACITY_TOOL, CAPACITY_SERIES)
                if lifted
                else Asker(ask_of(adapter))
            )
            for target in chosen:
                for channel in CHANNELS:
                    tally.inference.add(run_series(asker, SqliteTruth(con), target, channel))
