"""The disclosure table of the independent-sets run: each tool by level, against its claim.

Each level has its own cases and a leak counts once, at its heaviest level: an L2 cut
that showed a value whole is added to L1's attacks, a value an L3 series recovered whole
has its own L1 column, and neither counts in its own level. The price table gives what
each inferred fact and each value recovered whole cost the attacker; the capacity table
gives the same for incognito-sql with its budgets lifted, and the hours its default
literal and probe budgets would make the attacker wait for as much as the series spent.
"""

from collections.abc import Sequence

from bench.external.claims import verdict
from bench.external.tally import Tally
from bench.profiles import claim_of, measured
from incognito_sql.assess.model import budgets_of
from incognito_sql.core.config import Limits
from incognito_sql.levels.infer import CHANNELS, WHOLE, wait

_HEAD = (
    "| Tool | Claimed | L1: attacks | L1: honest answers | L1: recovered by a series "
    "| L2: cuts " + "".join(f"| L3: {c} " for c in CHANNELS) + "| Verdict |"
)


def levels(tallies: Sequence[Tally]) -> str:
    """Return the table: leaks by level, the L3 facts by channel, and the verdict."""
    lines = [_HEAD, "|---" * (7 + len(CHANNELS)) + "|"]
    for t in sorted(tallies, key=lambda t: (t.info.rung, t.info.name)):
        if not t.ran:
            continue
        claim = claim_of(t.info)
        honest = sum(t.tasks.values())
        series = t.inference
        lines.append(
            f"| {t.info.name} | {claim.label()} | {_l1(t)} | {share(t.exposed, honest)} "
            f"| {share(series.whole, series.targets['prefix'])} | {share(t.cut_part, t.cuts)} "
            + "".join(f"| {series.share(c)} " for c in CHANNELS)
            + f"| {verdict(t, claim)} |"
        )
    return "\n".join(lines)


def prices(tallies: Sequence[Tally]) -> str:
    """Return the median queries and literals per value recovered whole and per fact."""
    head = "| Tool | L1: recovered by a series " + "".join(f"| L3: {c} " for c in CHANNELS) + "|"
    lines = [head, "|---" * (2 + len(CHANNELS)) + "|"]
    for t in sorted(tallies, key=lambda t: (t.info.rung, t.info.name)):
        if t.ran and any(t.inference.targets.values()):
            cells = [t.inference.price(c) for c in (WHOLE, *CHANNELS)]
            lines.append(f"| {t.info.name} " + "".join(f"| {c} " for c in cells) + "|")
    return "\n".join(lines)


def capacity(tallies: Sequence[Tally]) -> str:
    """Return each fact of the rows with the literal budget lifted: share, price, hours."""
    lines = [
        "| Tool | Fact | Inferred | Queries / literals | Hours at the default budget |",
        "|---|---|---|---|---|",
    ]
    for t in sorted((t for t in tallies if measured(t.info)), key=lambda t: t.info.name):
        series = t.inference
        rows = [("value whole", share(series.whole, series.targets["prefix"]))]
        rows += [(c, series.share(c)) for c in CHANNELS]
        for fact, inferred in rows:
            key = WHOLE if fact == "value whole" else fact
            lines.append(
                f"| {t.info.name} | {fact} | {inferred} | {series.price(key)} "
                f"| {hours(series.spends.get(key, []))} |"
            )
    return "\n".join(lines)


def hours(spends: Sequence[tuple[int, int]], limits: Limits | None = None) -> str:
    """Return the hours the default budgets make a median series wait, or '-'.

    ``spends`` are the literals and probes the budgets counted of each series; per
    budget the first window is free, each further one is waited for.
    """
    return wait(spends, budgets_of(limits or Limits()))


def _l1(t: Tally) -> str:
    """Return the L1 attacks, and the L2 cuts that showed a value whole."""
    raised = f" +{t.cut_whole} L2 cuts" if t.cut_whole else ""
    return share(t.leaked, t.attacks) + raised


def share(part: int, whole: int) -> str:
    """Return ``part`` of ``whole`` as a percentage with its counts."""
    return f"{part / whole:.1%} ({part}/{whole})" if whole else "-"
