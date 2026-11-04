"""Decoy canaries: never planted, shaped like the hidden ones, scanned in the same text.

A hit on a decoy can only be chance, so decoy hits are the noise floor of a row. The
floor is fair only if the decoys can be hit as often as the real canaries: the decoy set
has, for every kind (text, number, date) and length, as many canaries as the hidden set,
and so as many oracle windows. Decoys come from worlds of further seeds; a candidate is
dropped when the oracle finds it in this world's values or it shares a window with a
canary or decoy already taken.
"""

import re
from collections import Counter

from bench.oracle import DIGIT_WINDOW, WINDOW, leaks, windows
from bench.world import World, generate_world

FIRST_SEED = 16  # the decoy worlds are seeds 16, 17, ...
_SEEDS = 64  # more than enough: a seed gives about half of what one world needs
_DATE = re.compile(r"\d{4}-\d\d")


def kind(canary: str) -> str:
    """Return ``number`` (all digits), ``date`` (``YYYY-MM``) or ``text``."""
    if canary.isdigit():
        return "number"
    return "date" if _DATE.fullmatch(canary) else "text"


def _windows(canary: str) -> set[str]:
    width = DIGIT_WINDOW if kind(canary) == "number" else WINDOW
    return windows(canary.casefold(), width)


def decoys(world: World) -> frozenset[str]:
    """Return decoys matching ``world.forbidden`` by kind, length and window count."""
    planted = "\n".join(str(v) for t in world.stored for row in t.rows for v in row)
    need = Counter((kind(c), len(c)) for c in world.forbidden)
    taken = set().union(*map(_windows, world.forbidden | world.visible | world.row_hidden))
    found: set[str] = set()
    for seed in range(FIRST_SEED, FIRST_SEED + _SEEDS):
        candidates = sorted(generate_world(seed).forbidden)
        seen_here = set(leaks(planted, candidates))
        for canary in candidates:
            shape, pieces = (kind(canary), len(canary)), _windows(canary)
            if need[shape] and canary not in seen_here and taken.isdisjoint(pieces):
                need[shape] -= 1
                taken |= pieces
                found.add(canary)
        if not +need:
            return frozenset(found)
    msg = f"not enough decoys after {_SEEDS} seeds: {dict(+need)}"
    raise AssertionError(msg)
