"""The benchmark report: one row per tool and DBMS, a ranking, and Markdown tables."""

from dataclasses import dataclass, field

from bench.adapters.base import Info
from bench.schema import DIALECTS
from bench.score import Row

_NAMES = {"postgres": "Postgres", "sqlite": "SQLite", "mysql": "MySQL", "duckdb": "DuckDB"}
_NAMES["tsql"] = "SQL Server"


@dataclass
class Report:
    """Rows of every tool that ran, and of every tool that could not, with the reason."""

    rows: list[Row] = field(default_factory=list)

    def add(self, rows: list[Row]) -> None:
        """Append rows of another run."""
        self.rows.extend(rows)

    def not_run(self, info: Info, dialect: str, reason: str) -> None:
        """Record a tool that could not run on ``dialect``."""
        self.rows.append(Row(info, dialect, status="not_run", reason=reason))

    def ranking(self, dialect: str) -> list[str]:
        """Return the names of the tools that ran on ``dialect``, safest first.

        Leaks under attack decide first (hits the verdict calls noise count as none),
        then leaks under honest use, then utility.
        """
        ran = [r for r in self.rows if r.dialect == dialect and r.status == "ok"]
        ran.sort(key=lambda r: (_attacks(r), r.over_exposure, -r.utility, r.false_reject))
        return [r.info.name for r in ran]

    def markdown(self) -> str:
        """Return one table per DBMS, rows in ladder order."""
        out: list[str] = []
        for dialect in DIALECTS:
            rows = sorted((r for r in self.rows if r.dialect == dialect), key=_rung)
            if rows:
                out += [f"### {_NAMES[dialect]}", "", *_table(rows), ""]
        return "\n".join(out)


def _attacks(row: Row) -> float:
    """Attacker success as the ranking reads it: hits judged noise count as none."""
    return row.attacker_success if row.verdict == "leak" else 0.0


def _rung(row: Row) -> tuple[int, str]:
    return row.info.rung, row.info.name


_HEAD = (
    "| Tool | Attacker success | Hits real / decoy | Verdict | Over-exposure | Utility "
    "| False reject | Latency ms (median / p95) | Notes |"
)


def _table(rows: list[Row]) -> list[str]:
    lines = [_HEAD, "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r.status != "ok":
            lines.append(f"| {r.info.name} | not_run | | | | | | | {r.reason} |")
            continue
        median, p95 = r.latency()
        notes = [f"{r.refused} refused, {r.errors} errors of {r.cases} attacks"]
        if r.skipped:
            notes.append(f"{r.skipped} skipped")
        if r.listing_leak:
            notes.append("tool listing leaks")
        if r.whole:
            notes.append(f"{r.whole} with a hidden value whole")
        if r.examples:
            notes.append("e.g. " + ", ".join(f"`{e}`" for e in r.examples[:3]))
        lines.append(
            f"| {r.info.name} | {_share(r.attacker_success, r.leaked, r.cases)} "
            f"| {r.leaked} / {r.noise} | {r.verdict} "
            f"| {_share(r.over_exposure, r.exposed, r.tasks)} "
            f"| {_share(r.utility, r.correct, r.tasks)} "
            f"| {_share(r.false_reject, r.rejected, r.tasks)} "
            f"| {median:.1f} / {p95:.1f} | {'; '.join(notes)} |"
        )
    return lines


def _share(value: float, part: int, whole: int) -> str:
    return f"{value:.1%} ({part}/{whole})"
