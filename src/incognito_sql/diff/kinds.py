"""The kinds of a change between two declarations, and one change."""

from dataclasses import dataclass

WIDENED, NARROWED, CHANGED = "WIDENED", "NARROWED", "CHANGED"
__all__ = ["CHANGED", "NARROWED", "WIDENED", "Change"]


@dataclass(frozen=True)
class Change:
    """One difference between the two declarations."""

    kind: str
    where: str
    what: str

    def line(self) -> str:
        """Return the change as the report prints it."""
        return f"{self.kind} {self.where}: {self.what}"
