"""The audit log read line by line: per column, the queries that named it and the masks.

Only the fields ``ts``, ``outcome``, ``reason``, ``columns``, ``masked`` and ``probes``
are read; the tokenized SQL is never looked at. A line from before the log named columns
or counted probes counts apart, as does a line that is not JSON.
"""

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from incognito_sql.core.output.suspects import COMPUTED


@dataclass
class Usage:
    """What the log says of one column."""

    named: int = 0  # queries that named it
    outcomes: Counter[str] = field(default_factory=Counter)  # "ok", "rejected: <reason>"
    masked: Counter[str] = field(default_factory=Counter)  # answers with masked cells, by kind


@dataclass
class Journal:
    """The log over a period: usage by column and what could not be read by column."""

    columns: dict[str, Usage] = field(default_factory=dict)
    lines: int = 0  # lines in the period
    without_columns: int = 0  # lines written before the log named columns
    refused_unnamed: int = 0  # refused before its columns were resolved: syntax, allowlist
    computed_masked: Counter[str] = field(default_factory=Counter)  # masks of no base column
    unreadable: int = 0  # of any date
    probes: int = 0  # spent of the probe budget
    without_probes: int = 0  # lines written before the log counted probes

    def usage(self, column: str) -> Usage:
        """Return the usage of ``column``, an empty one if the log never named it."""
        return self.columns.setdefault(column, Usage())


def read(path: Path, since: datetime | None) -> Journal:
    """Read the log at ``path``; lines before ``since`` are left out. No log: an empty one."""
    journal = Journal()
    if not path.exists():
        return journal
    for line in _lines(path):
        try:
            entry = json.loads(line)
            at = datetime.fromisoformat(entry["ts"])
            at = at if at.tzinfo else at.replace(tzinfo=UTC)
        except (ValueError, KeyError, TypeError):
            journal.unreadable += 1
            continue
        if since is not None and at < since:
            continue
        journal.lines += 1
        _count(journal, entry)
    return journal


def _lines(path: Path) -> Iterator[str]:
    with path.open(encoding="utf-8") as fh:
        yield from (line for line in fh if line.strip())


def _count(journal: Journal, entry: dict[str, object]) -> None:
    columns = entry.get("columns")
    if not isinstance(columns, list):
        journal.without_columns += 1
        columns = []
    outcome = str(entry.get("outcome"))
    reason = entry.get("reason")
    key = outcome if outcome == "ok" or not reason else f"{outcome}: {reason}"
    if isinstance(entry.get("columns"), list) and not columns and outcome != "ok":
        journal.refused_unnamed += 1
    for column in columns:
        usage = journal.usage(str(column).lower())
        usage.named += 1
        usage.outcomes[key] += 1
    probes = entry.get("probes")
    if isinstance(probes, int) and not isinstance(probes, bool):
        journal.probes += probes
    else:
        journal.without_probes += 1
    masked = entry.get("masked")
    for item in masked if isinstance(masked, list) else []:
        column, _, kind = str(item).rpartition(": ")
        if column.startswith(COMPUTED):
            journal.computed_masked[kind or "?"] += 1
        else:
            journal.usage(column.lower()).masked[kind or "?"] += 1
