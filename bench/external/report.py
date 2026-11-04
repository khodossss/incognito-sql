"""The report of the independent-sets run: one row per tool, and what was taken."""

import datetime as dt
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from bench.external.levels import capacity, levels, prices, share
from bench.external.sources import Source
from bench.external.tally import Tally
from bench.profiles import measured

SETS = (("spider", "Spider dev"), ("bird", "BIRD Mini-Dev"), ("securesql", "SecureSQL safe"))
_HEAD = (
    "| Tool | Attacks with a leak | Honest answers with a leak "
    + "".join(f"| Utility: {name} " for _, name in SETS)
    + "| False reject | Notes |"
)


@dataclass
class Taken:
    """What the run took from each set, and what it left out."""

    databases: dict[str, list[str]] = field(default_factory=dict)  # set -> databases
    tasks: Counter[str] = field(default_factory=Counter)
    left_out: Counter[tuple[str, str]] = field(default_factory=Counter)  # (set, why)
    attacks: Counter[str] = field(default_factory=Counter)  # SecureSQL label -> samples
    safe_samples: int = 0
    rows_only: int = 0  # SecureSQL samples under a condition no rule expresses, not run
    conditions: int = 0
    row_conditions: int = 0  # of ``conditions``, those that hide rows or cells


def table(tallies: Sequence[Tally]) -> str:
    """Return the result table, tools in ladder order."""
    lines = [_HEAD, "|---" * (5 + len(SETS)) + "|"]
    for t in sorted(tallies, key=lambda t: (t.info.rung, t.info.name)):
        if measured(t.info):  # runs the series only: its own table
            continue
        if not t.ran:
            why = "; ".join(t.skipped) or "not run"
            lines.append(f"| {t.info.name} | not_run |" + " |" * (2 + len(SETS)) + f" {why} |")
            continue
        total = sum(t.tasks.values())
        utility = "".join(f"| {share(t.correct[k], t.tasks[k])} " for k, _ in SETS)
        lines.append(
            f"| {t.info.name} | {share(t.leaked, t.attacks)} | {share(t.exposed, total)} "
            f"{utility}| {share(t.rejected, total)} | {_notes(t)} |"
        )
    return "\n".join(lines)


def _notes(t: Tally) -> str:
    notes = [f"{t.attack_refused} attacks refused whole, {t.errors} errors"]
    total = t.ran + sum(t.skipped.values())
    for why, works in sorted(t.skipped.items()):
        notes.append(f"not run on {works} of {total} databases and conditions: {why}")
    if t.listing:
        notes.append(f"tool listing leaks in {t.listing} databases")
    if t.examples:
        notes.append("leaks e.g. " + ", ".join(f"`{e}`" for e in t.examples[:3]))
    if t.exposed_examples:
        notes.append("honest leaks e.g. " + ", ".join(f"`{e}`" for e in t.exposed_examples[:3]))
    if t.partial or t.partial_exposed:
        notes.append(f"parts of values in {t.partial} attacks, {t.partial_exposed} honest answers")
    if t.partial_examples:
        notes.append("L2 e.g. " + ", ".join(f"`{e}`" for e in t.partial_examples[:3]))
    return "; ".join(notes)


def _why(taken: Taken, key: str) -> str:
    reasons = sorted((why, n) for (kind, why), n in taken.left_out.items() if kind == key)
    return ", ".join(f"{n} {why}" for why, n in reasons) or "none"


def fills(tallies: Sequence[Tally], taken: Taken, sources: Sequence[Source]) -> dict[str, str]:
    """Return the template fills of the independent-sets section."""
    pinned = ", ".join(f"{s.name} (`{s.file}`, sha256 `{s.sha256[:12]}`)" for s in sources)
    labels = ", ".join(f"{k} {v}" for k, v in sorted(taken.attacks.items()))
    sets = [
        f"- **{name}**: {taken.tasks[key]} questions with a reference answer on "
        f"{len(taken.databases.get(key, []))} databases "
        f"({', '.join(taken.databases.get(key, [])) or '-'}); left out: {_why(taken, key)}"
        for key, name in SETS[:2]
    ]
    sets.append(
        f"- **SecureSQL**: {sum(taken.attacks.values())} attack samples ({labels}) and "
        f"{taken.safe_samples} safe samples ({taken.tasks['securesql']} queries with a "
        f"reference; left out: {_why(taken, 'securesql')}) under {taken.conditions} "
        f"conditions ({taken.row_conditions} of them hide rows or cells by the gateway's "
        f"rules on rows; a tool that expresses no such rule is not run under them); "
        f"{taken.rows_only} samples under conditions no rule expresses are not run"
    )
    return {
        "ext_date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "ext_sources": pinned,
        "ext_sets": "\n".join(sets),
        "ext_table": table(tallies),
        "ext_levels": levels(tallies),
        "ext_prices": prices(tallies),
        "ext_capacity": capacity(tallies),
    }
