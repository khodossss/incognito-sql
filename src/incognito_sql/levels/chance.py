"""How likely a run of right answers is by chance: one-sided, at p = 1/2."""

import math

SIGNIFICANCE = 0.05


def chance_of(real: int, decoy: int) -> float:
    """One-sided chance of at least ``real`` of ``real + decoy`` fair coin flips."""
    n = real + decoy
    return sum(math.comb(n, k) for k in range(real, n + 1)) / float(2**n)
