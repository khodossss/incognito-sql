"""Is an answer the reference answer: the utility metric of ``bench/tasks.py``, generalised.

Rows are compared as multisets (in order when the query is ordered), numbers normalised
as ``bench.tasks.normal`` does. In an opaque column (a hidden value in the reference)
the answer may show any value, as long as reference values and shown values pair one to
one: one shared placeholder for two people is wrong, and so are two values for one
person. A NULL pairs only with NULL. ``bench/tasks.py`` pairs rows by their other
columns, which hand-written tasks guarantee to be a key; a set's query does not, so the
pairing is found by colour refinement: every value is coloured by the rows it is in,
rows by the colours of their values, until the colours are stable, on both sides at
once. Two sides that end with the same coloured rows are equal up to renaming the
opaque values; refinement can only accept wrongly a pairing between values that no row
tells apart.
"""

from collections import Counter
from collections.abc import Sequence

from bench.tasks import normal

Row = tuple[object, ...]
_ROUNDS = 16


def correct(
    expect: Sequence[Sequence[object]],
    rows: Sequence[Sequence[object]] | None,
    opaque: frozenset[int],
    *,
    ordered: bool,
) -> bool:
    """Tell whether ``rows`` answer a query whose reference is ``expect``."""
    if rows is None or len(rows) != len(expect):
        return False
    width = {len(r) for r in [*expect, *rows]}
    if len(width) > 1:
        return False
    keys = _coloured([list(expect), list(rows)], opaque)
    if ordered:
        return keys[0] == keys[1]
    return Counter(keys[0]) == Counter(keys[1])


def _coloured(sides: list[list[Sequence[object]]], opaque: frozenset[int]) -> list[list[Row]]:
    """Return each side's rows with plain cells normalised and opaque cells coloured."""
    plain = [
        [tuple(normal(v) for i, v in enumerate(r) if i not in opaque) for r in side]
        for side in sides
    ]
    columns = sorted(opaque)
    colour: list[dict[tuple[int, object], int]] = [
        {(c, _key(r[c])): int(r[c] is None) for r in side for c in columns} for side in sides
    ]
    count = -1
    for _ in range(_ROUNDS):
        rows = _rows(sides, plain, colour, columns)
        names: dict[object, int] = {}
        nxt: list[dict[tuple[int, object], int]] = []
        for side, side_rows, old in zip(sides, rows, colour, strict=True):
            seen: dict[tuple[int, object], list[Row]] = {}
            for r, coloured in zip(side, side_rows, strict=True):
                for c in columns:
                    seen.setdefault((c, _key(r[c])), []).append(coloured)
            paint = {}
            for key, among in seen.items():
                signature = (key[0], old[key], tuple(sorted(map(repr, among))))
                paint[key] = names.setdefault(signature, len(names))
            nxt.append(paint)
        colour = nxt
        if len(names) == count:
            break
        count = len(names)
    return _rows(sides, plain, colour, columns)


def _rows(
    sides: list[list[Sequence[object]]],
    plain: list[list[Row]],
    colour: list[dict[tuple[int, object], int]],
    columns: list[int],
) -> list[list[Row]]:
    return [
        [
            p + tuple(paint[(c, _key(r[c]))] for c in columns)
            for r, p in zip(side, flat, strict=True)
        ]
        for side, flat, paint in zip(sides, plain, colour, strict=True)
    ]


def _key(value: object) -> object:
    """Return a hashable key of a cell: a list or a dict in an answer is still a value."""
    return value if isinstance(value, str | int | float | bool | None) else repr(value)
