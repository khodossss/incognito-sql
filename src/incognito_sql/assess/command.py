"""`incognito-sql assess`: its arguments, the run, the report and the exit code."""

import argparse
import sys
from pathlib import Path

from incognito_sql.assess.model import Source
from incognito_sql.assess.report import as_json, as_text, broken
from incognito_sql.assess.run import assess
from incognito_sql.core.config import Declaration

EXIT_BROKEN = 1
EXIT_FAILED = 2


def add_assess_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add `assess` and its options to the command line."""
    command = commands.add_parser(
        "assess", help="judge the disclosure levels of this database under its profile"
    )
    command.add_argument("--config", type=Path, required=True, help="the service's declaration")
    command.add_argument("--env-file", type=Path, help="KEY=VALUE secrets for unset variables")
    command.add_argument("--targets", type=int, default=3, help="values probed per column")
    command.add_argument(
        "--capacity", action="store_true", help="also measure with the literal budget lifted"
    )
    command.add_argument("--json", action="store_true", help="print the report as JSON")
    command.add_argument(
        "--fail-on", choices=["breaks"], help="exit 1 when a column breaks its profile's claim"
    )


def run_assess(args: argparse.Namespace, decl: Declaration, dsn: str, key: bytes) -> int:
    """Assess, print the report on stdout, return the exit code.

    A failure is named by its type alone: a database error quotes its query's
    parameters, and the series' probes are made from the values.
    """
    try:
        result = assess(
            Source(args.config, decl, dsn, key), count=args.targets, capacity=args.capacity
        )
    except Exception as exc:  # noqa: BLE001 -- any failure: never its message
        sys.stderr.write(f"incognito-sql: assess failed: {type(exc).__name__}\n")
        return EXIT_FAILED
    sys.stdout.write((as_json(result) if args.json else as_text(result)) + "\n")
    return EXIT_BROKEN if args.fail_on == "breaks" and broken(result) else 0
