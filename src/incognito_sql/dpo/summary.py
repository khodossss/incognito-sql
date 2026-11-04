"""One row per column: its class and claim, what `assess` measured, what the log shows."""

from collections import Counter
from typing import Any

from incognito_sql.core.config import ColumnClass, Declaration
from incognito_sql.core.config.model import column_operations, column_profile
from incognito_sql.core.config.protection import opens
from incognito_sql.dpo.journal import Journal

UNNAMED = "hidden (not in the config)"
_CLAIMS = {
    ColumnClass.OPEN: "shown as is",
    ColumnClass.QUASI: "shown as is",
    ColumnClass.FREE_TEXT: "hidden",
    ColumnClass.SECRET: "hidden everywhere, the cards included",
}
_MEASURED = ("verdict", "L1 cuts", "L1 series", "L2 cuts", "hidden: refused")


def _claim(decl: Declaration, name: str, cls: ColumnClass | None) -> tuple[str, str]:
    """Return (profile, what the model may learn) of a column by its class and profile."""
    if cls is None:
        return "-", "nothing: every query naming it is refused"
    if cls is not ColumnClass.IDENTIFIER:
        return "-", _CLAIMS[cls]
    table, column = name.split(".", 1)
    profile = column_profile(decl, table, column)
    channels = [
        str(leak).removeprefix("L3 ") for leak in opens(column_operations(decl, table, column))
    ]
    opened = ", ".join(channels) or "none"
    return profile, f"a token, never the value whole; facts by a series: {opened}"


def _counts(counter: Counter[str]) -> str:
    return ", ".join(f"{key} {n}" for key, n in sorted(counter.items())) or "-"


def _measured(found: dict[str, Any], lifted: dict[str, Any]) -> str:
    parts = [f"{k} {found[k]}" for k in _MEASURED if k in found]
    if lifted:  # a channel the profile closes, read with the budget lifted, is a hole
        parts.append(f"budget lifted: verdict {lifted.get('verdict')}")
        parts.append(f"hours whole {lifted.get('hours whole', '-')}")
    return "; ".join(parts) or "-"


def rows(
    decl: Declaration, journal: Journal, assessed: dict[str, Any] | None
) -> list[dict[str, str]]:
    """Return the report's rows: every named column, then those only the log or assess saw."""
    named = {f"{t}.{c}": cls for t, cols in decl.columns.items() for c, cls in cols.items()}
    measured = {
        str(r["column"]).lower(): r
        for part in ("columns", "hidden")
        for r in (assessed or {}).get(part, [])
    }
    lifted = {str(r["column"]).lower(): r for r in (assessed or {}).get("capacity", [])}
    out = []
    for name in sorted(named) + sorted((set(journal.columns) | set(measured)) - set(named)):
        cls = named.get(name)
        profile, claim = _claim(decl, name, cls)
        usage = journal.usage(name)
        found = measured.get(name, {})
        out.append(
            {
                "column": name,
                "class": cls.value if cls is not None else UNNAMED,
                "profile": profile,
                "the model may learn": claim,
                "measured": _measured(found, lifted.get(name, {})),
                "queries naming it": str(usage.named),
                "outcomes": _counts(usage.outcomes),
                "answers with masked cells": _counts(usage.masked),
            }
        )
    return out
