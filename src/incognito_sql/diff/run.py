"""The `diff` command: print the changes; with `--ci`, exit 1 on any widening.

Only the two files are read, never the database.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from incognito_sql.core.config import Declaration, load_declaration
from incognito_sql.diff.changes import changes
from incognito_sql.diff.kinds import WIDENED
from incognito_sql.problems import quiet_problem

if TYPE_CHECKING:
    import argparse

EXIT_WIDENED = 1
EXIT_USAGE = 2


def add_diff_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the `diff` subcommand."""
    diff = commands.add_parser("diff", help="what a new declaration shows the model more or less")
    diff.add_argument("old", type=Path, help="the declaration in use")
    diff.add_argument("new", type=Path, help="the declaration proposed")
    diff.add_argument("--ci", action="store_true", help="exit 1 if anything is widened")


def run_diff(old_path: Path, new_path: Path, *, ci: bool) -> int:
    """Print every change; with ``ci``, exit 1 if any widens what the model sees."""
    try:
        old, new = _load(old_path, "old"), _load(new_path, "new")
    except ValueError as exc:
        sys.stderr.write(f"incognito-sql: {exc}\n")
        return EXIT_USAGE
    found = changes(old, new)
    sys.stdout.writelines(f"{c.line()}\n" for c in found)
    widened = sum(c.kind == WIDENED for c in found)
    sys.stdout.write(f"{len(found)} changes, {widened} widened\n")
    return EXIT_WIDENED if ci and widened else 0


def _load(path: Path, which: str) -> Declaration:
    try:
        return load_declaration(path)
    except Exception as exc:  # noqa: BLE001 -- file, YAML or schema: any is a bad config
        msg = f"cannot read the {which} declaration: {quiet_problem(exc)}"
        raise ValueError(msg) from None
