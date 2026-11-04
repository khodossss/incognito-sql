"""Render ``docs/benchmark.md`` from the report and the fixed method text.

The method, metrics and limits live in ``bench/benchmark.md.in``; this module fills in
the run facts, the result tables, the tools' provenance and what did not run.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from bench.external.section import carried
from bench.report import Report

if TYPE_CHECKING:
    from bench.adapters.base import Info

TEMPLATE = Path(__file__).parent / "benchmark.md.in"


def render(report: Report, facts: dict[str, str], previous: str = "") -> str:
    """Return the whole document for this run.

    The independent-sets section is another run's (``bench.external.run``): it is kept
    from ``previous``, the document this one replaces.
    """
    text = TEMPLATE.read_text(encoding="utf-8")
    fills = {
        **facts,
        "tables": report.markdown(),
        "tools": _tools(report),
        "not_run": _not_run(report),
    }
    for key, value in fills.items():
        text = text.replace("{{" + key + "}}", value)
    return carried(text, previous)


def _tools(report: Report) -> str:
    seen: dict[str, Info] = {}
    for row in sorted(report.rows, key=lambda r: r.info.rung):
        seen.setdefault(row.info.name, row.info)
    lines = [
        "| Tool | Mechanism | Source | Version | License | Installed | Run | Tool called |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i in seen.values():
        call = f"`{i.tool}({i.arguments})`"
        lines.append(
            f"| {i.name} | {i.mechanism} | {i.source or '-'} | {i.version or '-'} "
            f"| {i.license or '-'} | `{i.install}` | `{i.command}` | {call} |"
        )
    return "\n".join(lines)


def _not_run(report: Report) -> str:
    rows = [r for r in report.rows if r.status != "ok"]
    if not rows:
        return "Every tool ran on every DBMS it supports."
    return "\n".join(f"- **{r.info.name}** on {r.dialect}: {r.reason}." for r in rows)
