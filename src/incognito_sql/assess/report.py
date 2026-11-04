"""The assessment as the operator reads it: counts per column and level, never a value."""

import json

from incognito_sql.assess.model import Assessment, ColumnLevels, HiddenColumn
from incognito_sql.levels.infer import CHANNELS, HOURS_LEGEND, WHOLE


def _row(c: ColumnLevels) -> dict[str, object]:
    series = c.inference
    row: dict[str, object] = {
        "column": c.name,
        "profile": c.profile,
        "L1 cuts": f"{c.whole}/{c.cuts}",
        "L1 series": f"{series.whole}/{series.targets['prefix']}",
        "L2 cuts": f"{c.parts}/{c.cuts}",
        **{f"L3 {ch}": series.share(ch) for ch in CHANNELS},
        "price whole": series.price(WHOLE),
    }
    if c.measure:  # what the config's own budget would make the attacker wait
        row["hours whole"] = series.hours(WHOLE, c.budgets)
    row["verdict"] = c.verdict()
    return row


def _hidden(c: HiddenColumn) -> dict[str, object]:
    return {"column": c.name, "hidden: refused": f"{c.refused}/{c.cuts}", "verdict": c.verdict()}


def as_dict(result: Assessment) -> dict[str, list[dict[str, object]]]:
    """Return the report as data: identifier columns, hidden ones, then the budget lifted."""
    return {
        "columns": [_row(c) for c in result.columns],
        "hidden": [_hidden(c) for c in result.hidden],
        "capacity": [_row(c) for c in result.capacity],
    }


def as_json(result: Assessment) -> str:
    """Return the report as JSON."""
    return json.dumps(as_dict(result), ensure_ascii=False, indent=2)


def as_text(result: Assessment) -> str:
    """Return the report as Markdown tables: verdicts first, capacity after."""
    parts = []
    for title, rows in as_dict(result).items():
        if not rows:
            continue
        head = list(rows[0])
        lines = [f"## {title}", "", "| " + " | ".join(head) + " |", "|---" * len(head) + "|"]
        lines += ["| " + " | ".join(str(r[k]) for k in head) + " |" for r in rows]
        if "hours whole" in head:
            lines += ["", HOURS_LEGEND]
        parts.append("\n".join(lines))
    return "\n\n".join(parts) or "no identifier column of an entity table to assess"


def broken(result: Assessment) -> bool:
    """Tell whether a column breaks its profile's claim, with the budget lifted too.

    Lifted, a closed channel inferred is a hole of the policy the budget hid.
    """
    verdicts = [c.verdict() for c in [*result.columns, *result.capacity]]
    verdicts += [c.verdict() for c in result.hidden]
    return any(v.startswith("breaks") for v in verdicts)
