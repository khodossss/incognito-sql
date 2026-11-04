"""The `setup` command: the wizard, in the human's own terminal only."""

import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

from incognito_sql.setup.cases import CASES, case
from incognito_sql.wizard.prompts import Prompter
from incognito_sql.wizard.walk import Call, Stopped, walk

if TYPE_CHECKING:
    import argparse

EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


def add_setup_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the `setup` subcommand."""
    setup = commands.add_parser("setup", help="set the server up step by step, in a terminal")
    setup.add_argument("--case", choices=[c.name for c in CASES], help="skip the first question")
    setup.add_argument("--from", dest="start", metavar="STEP", help="go on from this step")


def run_setup(
    name: str | None,
    start: str | None,
    *,
    terminal: bool,
    prompter: Callable[[], Prompter],
    call: Call,
) -> int:
    """Walk one case with the human; refuse before any question without a terminal."""
    if not terminal:  # an agent or a pipe: the setup's questions are the human's
        return _fail("setup asks its questions in a terminal; an agent reads `incognito-sql guide`")
    if start is not None and name is None:
        return _fail("--from goes with --case")
    if start is not None and start not in (s.id for s in case(name or "").steps):
        return _fail("--from names no step of this case: see `incognito-sql guide --case`")
    ask = prompter()
    if name is None:
        ask.tell("Cases:")
        for one in CASES:
            ask.tell(f"  {one.name}: {one.choose_when}")
        name = ask.one("Which case is yours?", [c.name for c in CASES], CASES[0].name)
    try:
        walk(case(name), ask, call, start)
    except Stopped as exc:
        return exc.code
    except (KeyboardInterrupt, EOFError):  # Ctrl+C, or the input closed
        sys.stderr.write("\nincognito-sql: setup stopped\n")
        return EXIT_INTERRUPTED
    ask.tell("\nThe setup is done.")
    return 0


def _fail(message: str) -> int:
    sys.stderr.write(f"incognito-sql: {message}\n")
    return EXIT_USAGE
