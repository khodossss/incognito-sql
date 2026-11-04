"""`incognito-sql report`: its arguments, the period, and the report on stdout."""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from incognito_sql.core.config import config_problem, load_declaration
from incognito_sql.dpo.journal import Journal, read
from incognito_sql.dpo.summary import rows
from incognito_sql.levels.infer import HOURS_LEGEND
from incognito_sql.wiring import audit_path

DAYS = 30
EXIT_USAGE = 2


def add_report_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add `report` and its options to the command line."""
    command = commands.add_parser(
        "report", help="what the model may learn of each column and what it asked, for a DPO"
    )
    command.add_argument("--config", type=Path, required=True, help="the service's declaration")
    command.add_argument("--assess", type=Path, help="a report written by `assess --json`")
    command.add_argument(
        "--since", default=None, help=f"YYYY-MM-DD, or `all`; the last {DAYS} days by default"
    )
    command.add_argument("--json", action="store_true", help="print the report as JSON")


def run_report(args: argparse.Namespace, now: datetime | None = None) -> int:
    """Print the report of the config's columns over the period; return the exit code."""
    try:
        decl = load_declaration(args.config)
        since, period = _period(args.since, now or datetime.now(UTC))
        assessed = json.loads(args.assess.read_text(encoding="utf-8")) if args.assess else None
        journal = read(audit_path(args.config), since)
    except Exception as exc:  # noqa: BLE001 -- a bad file or date: say which, never its content
        sys.stderr.write(f"incognito-sql: report: {config_problem(exc)}\n")
        return EXIT_USAGE
    table = rows(decl, journal, assessed)
    if args.json:
        sys.stdout.write(
            json.dumps({"period": period, **_tally(journal), "columns": table}, indent=2) + "\n"
        )
    else:
        sys.stdout.write(_text(period, journal, table) + "\n")
    return 0


def _period(since: str | None, now: datetime) -> tuple[datetime | None, str]:
    if since == "all":
        return None, "the whole audit log"
    start = now - timedelta(days=DAYS) if since is None else datetime.fromisoformat(since)
    start = start if start.tzinfo else start.replace(tzinfo=UTC)
    return start, f"since {start:%Y-%m-%d}" + (f" (the last {DAYS} days)" if since is None else "")


def _tally(journal: Journal) -> dict[str, Any]:
    return {
        "queries": journal.lines,
        "queries before the log named columns": journal.without_columns,
        "queries refused before naming a column": journal.refused_unnamed,
        "answers with masked computed columns": dict(journal.computed_masked),
        "probes spent": journal.probes,
        "queries before the log counted probes": journal.without_probes,
        "unreadable lines (any date)": journal.unreadable,
    }


def _text(period: str, journal: Journal, table: list[dict[str, str]]) -> str:
    head = list(table[0]) if table else ["column"]
    lines = [f"# Columns, {period}", ""]
    lines += [f"- {key}: {n}" for key, n in _tally(journal).items()]
    lines += ["", "| " + " | ".join(head) + " |", "|---" * len(head) + "|"]
    lines += ["| " + " | ".join(r[k] for k in head) + " |" for r in table]
    if any("hours whole" in r.get("measured", "") for r in table):
        lines += ["", HOURS_LEGEND]
    return "\n".join(lines)
