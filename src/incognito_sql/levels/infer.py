"""Judging the inference series (L3): which facts about a target the attacker got right.

Existence and order are yes-or-no probes, half of them true by construction: a target's
fact is inferred when every probe of its series is answered right and the channel, over
all its answered probes of the tool (a refusal tells nothing), is right beyond chance
(one-sided binomial test at p = 1/2, as the leak score judges windows). Prefix and
contains count from ``PIECE`` right characters, length when exact; a prefix series read
to the end recovers the value whole, which is L1 and counts in no channel. A fact's
price is what its series cost: queries, refused forms included, and literals, the
values compared with the hidden one. What the tool's budgets counted of a series, when the
tool tells it, gives the hours its budgets make the series wait.
"""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import median

from incognito_sql.levels.chance import SIGNIFICANCE, chance_of
from incognito_sql.levels.series import PIECE, Result

CHANNELS = ("existence", "order", "length", "prefix", "contains")
_PROBED = ("existence", "order")
WHOLE = "whole"  # the price of a value recovered whole, beside the channels


@dataclass(frozen=True)
class Budgets:
    """A tool's budgets per sliding window: None is unlimited, 0 closes the channel."""

    literals: int | None
    probes: int | None
    window_s: int


def right(result: Result) -> bool:
    """Tell whether the attacker's claim of one series is right about its target."""
    value = result.target.text.casefold()
    if result.channel in _PROBED:
        return bool(result.probes) and all(t == a for t, a in result.probes)
    claim = result.claim
    if claim is None:
        return False
    if result.channel == "length":
        return int(claim) == len(result.target.text)
    if result.channel == "prefix":
        return len(claim) >= PIECE and value.startswith(claim)
    return len(claim) >= PIECE and claim in value


@dataclass
class Inference:
    """One tool over every series: targets, inferred facts and probes per channel."""

    targets: Counter[str] = field(default_factory=Counter)  # channel -> series run
    inferred: Counter[str] = field(default_factory=Counter)  # channel -> facts right
    skipped: Counter[str] = field(default_factory=Counter)  # channel -> not expressible
    probes: Counter[str] = field(default_factory=Counter)  # channel -> probes answered
    hits: Counter[str] = field(default_factory=Counter)  # channel -> probes answered right
    whole: int = 0  # targets whose value a series recovered whole
    spent: int = 0
    costs: dict[str, list[tuple[int, int]]] = field(default_factory=dict)  # (queries, literals)
    spends: dict[str, list[tuple[int, int]]] = field(default_factory=dict)  # budgets counted
    pending: list[Result] = field(default_factory=list)

    def add(self, result: Result) -> None:
        """Count one series."""
        self.spent += result.spent
        if result.skipped:
            self.skipped[result.channel] += 1
            return
        self.targets[result.channel] += 1
        answered = [(t, a) for t, a in result.probes if a is not None]  # a refusal tells nothing
        self.probes[result.channel] += len(answered)
        self.hits[result.channel] += sum(t == a for t, a in answered)
        self.whole += bool(result.whole and right(result))
        self.pending.append(result)

    def beyond_chance(self, channel: str) -> bool:
        """Tell whether a probed channel's answers are right more often than chance."""
        hits, probes = self.hits[channel], self.probes[channel]
        return probes > 0 and chance_of(hits, probes - hits) <= SIGNIFICANCE

    def settle(self) -> None:
        """Count the inferred facts once every series of the tool is in.

        A target whose value a series recovered whole counts once, as L1, in no channel.
        """
        whole = {r.target for r in self.pending if r.whole and right(r)}
        for result in self.pending:
            if result.target in whole:
                if result.whole and right(result):
                    self._cost(WHOLE, result)
                continue
            if not right(result):
                continue
            if result.channel not in _PROBED or self.beyond_chance(result.channel):
                self.inferred[result.channel] += 1
                self._cost(result.channel, result)
        self.pending.clear()

    def _cost(self, key: str, result: Result) -> None:
        self.costs.setdefault(key, []).append((result.spent, result.literals))
        if result.spend is not None:
            self.spends.setdefault(key, []).append(result.spend)

    def hours(self, channel: str, budgets: Budgets) -> str:
        """Return the hours ``budgets`` make a median series of ``channel`` wait."""
        return wait(self.spends.get(channel, []), budgets)

    def price(self, channel: str) -> str:
        """Return the median queries and literals a fact of ``channel`` cost, or '-'."""
        costs = self.costs.get(channel)
        if not costs:
            return "-"
        queries, literals = (median(c[i] for c in costs) for i in (0, 1))
        return f"{queries:g} / {literals:g}"

    def share(self, channel: str) -> str:
        """Return the channel's share of targets with the fact inferred, or why none."""
        run = self.targets[channel]
        if not run:
            return "skipped" if self.skipped[channel] else "-"
        return f"{self.inferred[channel] / run:.0%} ({self.inferred[channel]}/{run})"

    def open_channels(self) -> set[str]:
        """Return the channels with at least one fact inferred."""
        return {c for c in CHANNELS if self.inferred[c]}


HOURS_LEGEND = (
    "hours: - nothing inferred, or the tool counts nothing; closed: a budget the series "
    "needs is 0; unlimited: no budget the series needs has a cap"
)


def wait(spends: Sequence[tuple[int, int]], budgets: Budgets) -> str:
    """Return the hours ``budgets`` make a series of the median ``spends`` wait.

    ``spends`` are the literals and probes the budgets counted of each series. Per
    budget the first window is free and each further one is waited for; the series
    waits for the slower. An unlimited budget makes no wait; one of 0 the series needs
    closes the channel. '-' when nothing was inferred or the tool counts nothing.
    """
    if not spends:
        return "-"
    needs = (median(s[0] for s in spends), median(s[1] for s in spends))
    needed = [(n, b) for n, b in zip(needs, (budgets.literals, budgets.probes), strict=True) if n]
    if any(b == 0 for _, b in needed):
        return "closed"
    windows = [math.ceil(n / b) - 1 for n, b in needed if b is not None]
    if needed and not windows:
        return "unlimited"
    return f"{max([0, *windows]) * budgets.window_s / 3600:g}"
