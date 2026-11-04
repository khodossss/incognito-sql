"""Our marking of a set's database (``bench/external/decl/<db>.yaml``): the only thing ours.

A file names the database and its set, the people tables (``entities``), and the class
of every column that is not ``open`` (a column the file does not list is open). The
classes are the gateway's (``identifier``, ``quasi``, ``free_text``, ``secret``) plus
``hidden``, a column left out of the gateway's declaration. ``conditions`` are the
SecureSQL security conditions on this database, each with the whole columns it closes
(``columns``) and the rows or cells it hides (``rows``: the gateway's ``row_rules``,
``{table, hide: [columns] | "*", where}``); ``rows_only`` are the conditions no rule
expresses, not run. A closed column is marked ``identifier`` under its condition. ``verified_open``
names shown columns whose values only look personal (codes, zip codes, an institution's
phone): the gateway's value mask leaves them alone, as an operator lists them after its
warning.
"""

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from bench.external.rowrule import RowRule

DECL = Path(__file__).parent / "decl"
CLASSES = frozenset({"identifier", "quasi", "free_text", "secret", "hidden", "open"})
SHOWN = frozenset({"open", "quasi"})  # values a client may see as they are
SETS = frozenset({"spider", "bird"})
_KEYS = frozenset({"db", "set", "entities", "columns", "conditions", "rows_only", "verified_open"})
Columns = dict[str, dict[str, str]]


@dataclass(frozen=True)
class Condition:
    """A SecureSQL security condition: the whole columns it closes, the rows it hides."""

    text: str
    columns: tuple[tuple[str, str], ...]
    rows: tuple[RowRule, ...] = ()


@dataclass(frozen=True)
class Marking:
    """The class of each column of one database, under at most one condition."""

    db: str
    source: str
    entities: tuple[tuple[str, str], ...]
    columns: Columns
    conditions: tuple[Condition, ...] = ()
    rows_only: tuple[str, ...] = ()
    verified_open: tuple[tuple[str, str], ...] = ()
    condition: Condition | None = field(default=None, compare=False)

    def cls(self, table: str, column: str) -> str:
        """Return the class of a column; unlisted columns are open."""
        return self.columns.get(table.lower(), {}).get(column.lower(), "open")

    def under(self, condition: Condition) -> "Marking":
        """Return this marking with the columns ``condition`` closes marked identifier."""
        columns = {t: dict(cols) for t, cols in self.columns.items()}
        for table, column in condition.columns:
            columns.setdefault(table, {})[column] = "identifier"
        return replace(self, columns=columns, condition=condition)

    @property
    def rules(self) -> tuple[RowRule, ...]:
        """Return the rules on rows in force: those of this marking's condition."""
        return self.condition.rows if self.condition else ()

    def listed(self) -> set[tuple[str, str]]:
        """Return every (table, column) the file or the condition names."""
        named = {(t, c) for t, cols in self.columns.items() for c in cols}
        named |= {pair for cond in self.conditions for pair in cond.columns}
        named |= {
            (rule.table, c) for cond in self.conditions for rule in cond.rows for c in rule.hide
        }
        return named | set(self.entities)

    def verified(self) -> dict[str, list[str]]:
        """Return the verified columns still shown under this marking's condition."""
        out: dict[str, list[str]] = {}
        for table, column in self.verified_open:
            if self.cls(table, column) in SHOWN:
                out.setdefault(table, []).append(column)
        return out


def load(path: Path) -> Marking:
    """Read one marking file; a malformed file raises ``ValueError``."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not set(raw) <= _KEYS or raw.get("set") not in SETS:
        msg = f"{path.name}: bad marking"
        raise ValueError(msg)
    columns: Columns = {
        str(t).lower(): {str(c).lower(): str(k) for c, k in (cols or {}).items()}
        for t, cols in (raw.get("columns") or {}).items()
    }
    if any(k not in CLASSES for cols in columns.values() for k in cols.values()):
        msg = f"{path.name}: unknown class"
        raise ValueError(msg)
    entities = tuple(
        (str(e["table"]).lower(), str(e["pk"]).lower()) for e in raw.get("entities") or []
    )
    conditions = tuple(_condition(c) for c in raw.get("conditions") or [])
    if any(not (c.columns or c.rows) for c in conditions):
        msg = f"{path.name}: a condition closes nothing"
        raise ValueError(msg)
    rows_only = tuple(str(t) for t in raw.get("rows_only") or [])
    verified = tuple(
        (str(t).lower(), str(c).lower())
        for t, cols in (raw.get("verified_open") or {}).items()
        for c in cols
    )
    marking = Marking(
        str(raw["db"]), str(raw["set"]), entities, columns, conditions, rows_only, verified
    )
    if any(marking.cls(t, c) not in SHOWN for t, c in verified):
        msg = f"{path.name}: verified_open names a column that is not shown"
        raise ValueError(msg)
    return marking


def _condition(raw: dict[str, Any]) -> Condition:
    columns = tuple(
        (str(t).lower(), str(col).lower())
        for t, cols in (raw.get("columns") or {}).items()
        for col in cols
    )
    rows = tuple(RowRule.read(r) for r in raw.get("rows") or [])
    return Condition(str(raw["text"]), columns, rows)


def load_all(directory: Path = DECL) -> list[Marking]:
    """Read every marking file, in name order; each database once."""
    markings = [load(p) for p in sorted(directory.glob("*.yaml"))]
    if len({m.db for m in markings}) != len(markings):
        msg = "a database is marked twice"
        raise ValueError(msg)
    return markings
