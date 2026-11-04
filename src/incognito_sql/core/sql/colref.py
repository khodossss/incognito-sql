"""The base column a value comes from, and how sensitive its class is."""

from dataclasses import dataclass

from incognito_sql.core.config import ColumnClass

HIDDEN_RANK = 3
_RANK: dict[ColumnClass | None, int] = {
    ColumnClass.OPEN: 0,
    ColumnClass.QUASI: 1,
    ColumnClass.IDENTIFIER: 2,
}


@dataclass(frozen=True)
class ColumnRef:
    """A base column (or `""`, `""` for a computed value) and its declared class."""

    table: str
    column: str
    cls: ColumnClass | None


COMPUTED = ColumnRef("", "", ColumnClass.OPEN)


def rank(cls: ColumnClass | None) -> int:
    """Order classes by sensitivity: hidden > identifier > quasi > open."""
    return _RANK.get(cls, HIDDEN_RANK)
