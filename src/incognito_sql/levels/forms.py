"""The forms of one question: the same fact asked in several shapes and places.

A defence may close a fact in one form and leave it open in another (``LIKE`` refused,
``substr`` of ``max`` over the column answered), so a question goes out in its forms
until one is answered (``Asker.ask_any``). The column stands bare in ``WHERE``, then
under ``max`` and under ``min`` in ``HAVING`` over the target's one row; text is compared
through ``lower`` where ``LIKE`` ignores case, so every form asks the same thing. Shapes
of one family keep their place in each list, so the form that answered last is tried
first on the next question of the series.
"""

from collections.abc import Callable, Sequence

from incognito_sql.levels.asker import literal
from incognito_sql.levels.target import Target

Shape = Callable[[str], str]  # the column's expression -> a condition on it
_AGGREGATES = ("max", "min")


def on_row(t: Target, shapes: Sequence[Shape]) -> list[str]:
    """Return the question about the target's row in every shape and place."""
    rows = f'FROM "{t.table}" WHERE "{t.key}" = {literal(t.row)}'
    column = f'"{t.column}"'
    bare = [f"SELECT count(*) {rows} AND {shape(column)}" for shape in shapes]
    under = [
        f'SELECT count(*) FROM (SELECT 1 {rows} GROUP BY "{t.key}" HAVING '  # noqa: S608
        f"{shape(f'{aggregate}({column})')}) AS q"
        for aggregate in _AGGREGATES
        for shape in shapes
    ]
    return bare + under


def in_column(t: Target, value: object) -> list[str]:
    """Return the question whether ``value`` is anywhere in the target's column."""
    rows = f'SELECT count(*) FROM "{t.table}" WHERE "{t.column}"'  # noqa: S608
    return [f"{rows} = {literal(value)}", f"{rows} IN ({literal(value)})"]


def prefix(p: str) -> list[Shape]:
    """Return the shapes of: the value starts with ``p`` (lower case)."""
    return [
        lambda e: f"{e} LIKE {literal(p + '%')}",
        lambda e: f"lower(substr({e}, 1, {len(p)})) = {literal(p)}",
        lambda e: f"instr(lower({e}), {literal(p)}) = 1",
    ]


def whole(p: str) -> list[Shape]:
    """Return the shapes of: the value is ``p`` (lower case), in the families of ``prefix``."""
    return [
        lambda e: f"{e} LIKE {literal(p)}",
        lambda e: f"lower({e}) = {literal(p)}",
        lambda e: f"instr(lower({e}), {literal(p)}) = 1 AND length({e}) = {len(p)}",
    ]


def contains(s: str) -> list[Shape]:
    """Return the shapes of: the value holds ``s`` (lower case)."""
    return [
        lambda e: f"{e} LIKE {literal('%' + s + '%')}",
        lambda e: f"instr(lower({e}), {literal(s)}) > 0",
    ]


def length(op: str, n: int) -> list[Shape]:
    """Return the shape of: the value's length compared by ``op`` with ``n``."""
    return [lambda e: f"length({e}) {op} {n}"]


def below(probe: object) -> list[Shape]:
    """Return the shapes of: the value is below ``probe``."""
    return [
        lambda e: f"{e} < {literal(probe)}",
        lambda e: f"NOT ({e} >= {literal(probe)})",
    ]
