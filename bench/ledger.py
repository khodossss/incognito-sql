"""The ledger table: typed identifier columns, each value a canary the oracle can match."""

import random

from bench.canary import CanaryMint

N_LEDGER = 6
PLACES = ("north", "south", "east")
Rows = tuple[tuple[object, ...], ...]


def ledger_rows(
    mint: CanaryMint, rng: random.Random, moods: tuple[str, str]
) -> tuple[Rows, dict[str, list[str]]]:
    """Rows of typed identifiers, and the canaries of the columns only some DBMS have."""
    rows = []
    only: dict[str, list[str]] = {"seen_tz": [], "cash": [], "huge": [], "unsigned_no": []}
    only["mood"] = list(moods)
    for i in range(1, N_LEDGER + 1):
        amounts = (mint.decimal(10, 2), mint.decimal(10, 2))
        born, seen_at = mint.moment().date(), mint.moment().replace(tzinfo=None)
        before = len(mint.forbidden)
        seen_tz = mint.moment()
        only["seen_tz"] += mint.forbidden[before:]
        cash = mint.decimal(10, 2)
        only["cash"].append(mint.forbidden[-1])
        huge, unsigned = mint.digits(25), mint.digits(20, "10")
        only["huge"].append(huge)
        only["unsigned_no"].append(unsigned)
        typed = (*amounts, born, seen_at, seen_tz, cash, int(huge), int(unsigned))
        rows.append((i, i, *typed, moods[i % 2], rng.choice(PLACES)))
    return tuple(rows), only
