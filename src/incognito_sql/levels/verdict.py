"""A tool's leaks by level against what it claims: the one place the verdict is read.

The benchmark and ``assess`` bring their own counts to ``Leaks``: a value shown whole,
a value a series read whole, a part shown, and the L3 channels with a fact inferred.
"""

from dataclasses import dataclass

from incognito_sql.levels.infer import CHANNELS


@dataclass(frozen=True)
class Leaks:
    """What a run found, level by level."""

    shown: bool  # a hidden value shown whole
    read_whole: bool  # a value a series recovered whole
    parts: bool  # a part of a hidden value shown
    inferred: frozenset[str]  # L3 channels with a fact inferred


def verdict(leaks: Leaks, level: str, opened: frozenset[str], *, series: bool = True) -> str:
    """Return whether ``leaks`` keep a claim of ``level`` with ``opened`` channels.

    ``level`` is ``none``, ``L1``, ``L2`` or ``L3``. ``series``: a value read whole by a
    series breaks the claim too (a masking tool promises nothing about inference).
    """
    if level == "none":
        return "no claim"
    broken = []
    if leaks.shown or (series and leaks.read_whole):
        broken.append("L1")
    if level in {"L2", "L3"} and leaks.parts:
        broken.append("L2")
    closed = leaks.inferred - opened
    if level == "L3" and closed:
        broken.append("L3 (" + ", ".join(c for c in CHANNELS if c in closed) + ")")
    if broken:
        return "breaks " + "; ".join(broken)
    return "holds" if level != "L1" else "holds L1; L2, L3 at one level, not claimed"
