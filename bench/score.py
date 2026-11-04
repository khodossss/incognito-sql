"""Score one adapter: the attack corpus through every channel, then the utility tasks.

The oracle (``bench.oracle.leaks``) is the only leak judge; attacks and honest tasks are
both scanned in the answer and the side channels. Side channels lose their clock fields
first (wall-clock stamps and durations carry no query data, but their digits would hit
6-digit numeric windows by chance). Decoys (``bench.decoy``), canaries never planted,
are scanned in the same text: their hits are the noise floor of the count.
"""

import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field

from bench.adapters.base import ANSWERED, ERROR, REFUSED, SKIPPED, Adapter, Info, Outcome
from bench.cases import Case
from bench.oracle import leaks, whole
from bench.tasks import Task, correct
from bench.templates import expand
from incognito_sql.levels.chance import SIGNIFICANCE, chance_of

_CLOCK_JSON = re.compile(
    r'"(?:ts|timestamp|time|\w*_ms|elapsed\w*|duration\w*)"\s*:\s*("[^"]*"|[-\d.eE+]+)'
)
_CLOCK_PAIR = re.compile(r"\b(?:\w*_ms|elapsed\w*|duration\w*)=\S+")
_LOG_STAMP = re.compile(r"(?m)^\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d[,.]?\d*")
# The audit line's keyed digest of the line before: random letters, data of no row.
_CHAIN_JSON = re.compile(r'"prev"\s*:\s*"[^"]*"')


def unclocked(text: str) -> str:
    """Drop what differs by chance: timing keys, ``*_ms=`` pairs, stamps, the audit chain."""
    text = _CHAIN_JSON.sub('"chain": 0', _CLOCK_JSON.sub('"clock": 0', text))
    return _LOG_STAMP.sub("", _CLOCK_PAIR.sub("", text))


def _beyond_chance(row: "Row") -> bool:
    return chance_of(row.leaked, row.noise) <= SIGNIFICANCE


@dataclass
class Row:
    """One tool on one DBMS: counts behind every metric of the report."""

    info: Info
    dialect: str
    status: str = "ok"  # or "not_run"
    reason: str = ""
    cases: int = 0
    skipped: int = 0
    leaked: int = 0
    refused: int = 0
    errors: int = 0
    noise: int = 0
    whole: int = 0
    listing_leak: bool = False
    tasks: int = 0
    correct: int = 0
    exposed: int = 0
    rejected: int = 0
    latencies: list[float] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

    @property
    def attacker_success(self) -> float:
        """Share of attack cases with a hidden canary in any channel."""
        if self.listing_leak:
            return 1.0  # the model reads the listing before any query
        return self.leaked / self.cases if self.cases else 0.0

    @property
    def verdict(self) -> str:
        """Say whether hidden-canary hits are a ``leak``, ``noise`` or ``none``.

        A hidden value shown whole is a leak. Window hits alone: decoys match the hidden
        canaries in kind and windows, so by chance a hit is as likely real as decoy, and
        real hits are a leak only when that chance is at most ``SIGNIFICANCE``. For a
        strict tool (ours) one hit is a leak.
        """
        evident = self.info.strict or self.whole or _beyond_chance(self)
        if self.listing_leak or (self.leaked and evident):
            return "leak"
        return "noise" if self.leaked else "none"

    @property
    def over_exposure(self) -> float:
        """Share of utility answers carrying a hidden canary the question did not hold."""
        return self.exposed / self.tasks if self.tasks else 0.0

    @property
    def utility(self) -> float:
        """Share of utility tasks answered with the reference result."""
        return self.correct / self.tasks if self.tasks else 0.0

    @property
    def false_reject(self) -> float:
        """Share of utility tasks the tool refused."""
        return self.rejected / self.tasks if self.tasks else 0.0

    def latency(self) -> tuple[float, float]:
        """Return the median and the 95th percentile of query time, in ms."""
        if len(self.latencies) < 2:  # noqa: PLR2004 -- quantiles need two points
            return (self.latencies or [0.0])[0], (self.latencies or [0.0])[0]
        return statistics.median(self.latencies), statistics.quantiles(self.latencies, n=20)[18]


def score(
    adapter: Adapter,
    corpus: Iterable[Case],
    tasks: Iterable[Task],
    hidden: tuple[frozenset[str], frozenset[str]],
) -> Row:
    """Run the corpus and the tasks through ``adapter``; ``hidden`` is (canaries, decoys)."""
    forbidden = hidden[0]
    row = Row(adapter.info, adapter.dialect)
    row.listing_leak = bool(leaks(adapter.static(), forbidden))
    applies = [case for case in corpus if _applies(case, adapter)]
    for case in [c for c in applies if not c.changes_session]:
        _case(row, adapter, case, hidden)
    for task in tasks:
        out, text = _sent(adapter, task.sql)
        row.tasks += 1
        row.latencies.append(out.ms)
        typed = set(leaks(task.sql, forbidden))  # the human's own literal is no exposure
        row.exposed += bool(leaks(text, forbidden - typed))
        row.rejected += out.status == REFUSED
        row.correct += out.status == ANSWERED and correct(task, out.rows)
    # Last: a case that switches the database or a session option must not change the
    # cases and tasks after it on a tool that keeps one session.
    for case in [c for c in applies if c.changes_session]:
        _case(row, adapter, case, hidden)
    return row


def _case(
    row: Row, adapter: Adapter, case: Case, hidden: tuple[frozenset[str], frozenset[str]]
) -> None:
    forbidden, decoys = hidden
    setup = "" if case.setup is None else _sent(adapter, case.setup)[1]
    out, text = _sent(adapter, case.sql)
    text = setup + text
    if out.status == SKIPPED:
        row.skipped += 1
        return
    _count(row, out)
    row.cases += 1
    if leaks(text, forbidden):
        row.leaked += 1
        row.whole += bool(whole(text, forbidden))
        if len(row.examples) < 5:  # noqa: PLR2004 -- a few names for the report
            row.examples.append(case.id)
    row.noise += bool(leaks(text, decoys))


def _sent(adapter: Adapter, sql: str) -> tuple[Outcome, str]:
    """Send a query; return it and the answer and side channels, clock fields dropped."""
    out = adapter.query(expand(sql, adapter.tokens))
    return out, "\n".join([out.text, *map(unclocked, adapter.channels().values()), ""])


def _applies(case: Case, adapter: Adapter) -> bool:
    mode = adapter.mode
    return adapter.dialect in case.dialects and (
        mode is None or case.runs_in(mode, adapter.dialect)
    )


def _count(row: Row, out: Outcome) -> None:
    row.latencies.append(out.ms)
    row.refused += out.status == REFUSED
    row.errors += out.status == ERROR
