"""What an assessment reads and what it found, column by column."""

from dataclasses import dataclass, field
from pathlib import Path

from incognito_sql.core.config import Declaration, Limits
from incognito_sql.levels.infer import Budgets, Inference
from incognito_sql.levels.verdict import Leaks, verdict


def budgets_of(limits: Limits) -> Budgets:
    """Return the literal and probe budgets of ``limits`` and their window."""
    return Budgets(limits.literal_budget, limits.probe_budget, limits.literal_window_s)


@dataclass(frozen=True)
class Source:
    """The service's settings: its declaration file and what it was read into."""

    config: Path
    decl: Declaration
    dsn: str
    key: bytes


@dataclass
class ColumnLevels:
    """What the oracles saw on one column: cuts that showed it, facts the series read."""

    table: str
    column: str
    profile: str
    opened: frozenset[str]  # L3 channels the profile declares open
    cuts: int = 0
    whole: int = 0  # cuts that showed a value whole
    parts: int = 0  # cuts that showed a part of one
    measure: bool = False  # the budgets lifted: values read whole are their capacity
    budgets: Budgets = field(default_factory=lambda: budgets_of(Limits()))  # the config's own
    inference: Inference = field(default_factory=Inference)

    @property
    def name(self) -> str:
        """Return ``table.column``."""
        return f"{self.table}.{self.column}"

    def verdict(self) -> str:
        """Return whether the column keeps its profile's claim, and what it broke."""
        leaks = Leaks(
            shown=bool(self.whole),
            read_whole=bool(self.inference.whole) and not self.measure,
            parts=bool(self.parts),
            inferred=frozenset(self.inference.open_channels()),
        )
        found = verdict(leaks, "L3", self.opened)
        if found == "holds" and not any(self.inference.targets.values()):
            return "holds cuts; no value to probe by a series"
        return found


@dataclass
class HiddenColumn:
    """A column the declaration does not name: every cut of it must be refused."""

    table: str
    column: str
    cuts: int = 0
    refused: int = 0

    @property
    def name(self) -> str:
        """Return ``table.column``."""
        return f"{self.table}.{self.column}"

    def verdict(self) -> str:
        """Return ``holds`` when every cut was refused."""
        return (
            "holds" if self.refused == self.cuts else f"breaks: {self.cuts - self.refused} answered"
        )


@dataclass
class Assessment:
    """Every identifier column under the default budget, and with it lifted if asked."""

    columns: list[ColumnLevels]
    capacity: list[ColumnLevels]
    hidden: list[HiddenColumn] = field(default_factory=list)
