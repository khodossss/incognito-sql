"""The verdict of the independent-sets run against each tool's claim (``bench.profiles``).

A masking competitor's L2 and L3 numbers compare tools at one level: they break nothing.
"""

from bench.external.tally import Tally
from bench.profiles import Claim, claim_of
from incognito_sql.levels.verdict import Leaks
from incognito_sql.levels.verdict import verdict as judged


def verdict(tally: Tally, claim: Claim) -> str:
    """Return whether the run kept the claim, and what it broke."""
    leaks = Leaks(
        shown=bool(tally.leaked or tally.exposed or tally.listing or tally.cut_whole),
        read_whole=bool(tally.inference.whole),
        parts=bool(tally.cut_part),
        inferred=frozenset(tally.inference.open_channels()),
    )
    return judged(leaks, claim.level, claim.open, series=claim.series)


def ours_broken(tally: Tally) -> bool:
    """Tell whether ``tally`` is incognito-sql's and broke L1: a value shown or read whole."""
    return tally.info.strict and verdict(tally, claim_of(tally.info)).startswith("breaks L1")
