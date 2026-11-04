"""The gateway's rule on rows, as our marking of a set's database writes it."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RowRule:
    """The gateway's rule on rows: where ``where`` is true or NULL, ``hide`` is NULL.

    ``hide`` is a tuple of columns, or empty for ``"*"``: the whole row is gone.
    Names are lower case.
    """

    table: str
    hide: tuple[str, ...]
    where: str

    @classmethod
    def read(cls, raw: dict[str, Any]) -> "RowRule":
        """Read ``{table, hide: [columns] | "*", where}`` from a marking file."""
        hide = raw["hide"]
        columns = () if hide == "*" else tuple(str(c).lower() for c in hide)
        return cls(str(raw["table"]).lower(), columns, str(raw["where"]))

    def hides(self, column: str) -> bool:
        """Tell whether the rule hides ``column`` in the rows it covers."""
        return not self.hide or column in self.hide

    def declared(self) -> dict[str, Any]:
        """Return the rule as the gateway's declaration writes it."""
        return {"table": self.table, "hide": list(self.hide) or "*", "where": self.where}
