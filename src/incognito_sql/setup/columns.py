"""The columns step: what init suggests for each column, and the declaration the human decides.

Both read and write files the setup made; no value of the database passes here, only names,
classes and init's reasons (a name hint, a sample that looks personal).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from incognito_sql.core.config import load_declaration
from incognito_sql.problems import quiet_problem

HIDDEN = "hidden"  # not listed: the model never sees it
_NAME = r'("(?:[^"\\]|\\.)*")'
_TABLE = re.compile(rf"^  {_NAME}:\s*$")
_COLUMN = re.compile(rf"^\s*#?\s*{_NAME}:\s*(\w+)\s*(?:#\s*PII\?:\s*(.*?))?(?:\s*#.*)?$")


@dataclass(frozen=True)
class Proposal:
    """A column, the class init suggests, and why (empty: no sign of personal data)."""

    table: str
    column: str
    suggested: str
    reason: str


def proposals(scaffold: Path) -> list[Proposal]:
    """Return a proposal per column of the scaffold init wrote, in its order."""
    found: list[Proposal] = []
    table: str | None = None
    in_columns = False
    for line in scaffold.read_text(encoding="utf-8").splitlines():
        if not line.startswith((" ", "#")):
            in_columns = line.startswith("columns:")
            table = None
            continue
        if not in_columns:
            continue
        if match := _TABLE.match(line):
            table = json.loads(match.group(1))
        elif table is not None and (match := _COLUMN.match(line)):
            name, cls, reason = json.loads(match.group(1)), match.group(2), match.group(3) or ""
            found.append(Proposal(table, name, cls, reason.strip()))
    return found


def apply_classes(
    config: Path, classes: dict[tuple[str, str], str], entities: list[tuple[str, str]]
) -> str | None:
    """Write the decided classes and entities into ``config``; return a problem, or None.

    A column decided ``hidden`` is left out. The file must load afterwards, or it is left
    as it was.
    """
    before = config.read_text(encoding="utf-8")
    raw: dict[str, Any] = yaml.safe_load(before) or {}
    columns: dict[str, dict[str, str]] = {}
    for (table, column), cls in classes.items():
        if cls != HIDDEN:
            columns.setdefault(table, {})[column] = cls
    raw["columns"] = columns
    raw["entities"] = [{"table": t, "pk": pk} for t, pk in entities]
    config.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), "utf-8")
    try:
        load_declaration(config)
    except Exception as exc:  # noqa: BLE001 -- schema: any is a bad decision
        config.write_text(before, encoding="utf-8")
        return quiet_problem(exc)
    return None
