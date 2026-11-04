"""The setup's commands on the command line: guide, skill, secret, env, set and the wizard."""

import argparse
import getpass
from collections.abc import Callable

from incognito_sql.setup.console import interactive
from incognito_sql.setup.env import add_env_parser, run_env
from incognito_sql.setup.guide import add_guide_parser, run_guide
from incognito_sql.setup.secret import Terminal, add_secret_parser, run_secret
from incognito_sql.setup.setkey import add_set_parser, run_set
from incognito_sql.setup.skill import Place, add_skill_parser, run_skill
from incognito_sql.setup.uservar import user_variable
from incognito_sql.wizard import arrows
from incognito_sql.wizard.run import add_setup_parser, run_setup


def _setup(args: argparse.Namespace) -> int:
    from incognito_sql.cli import main  # noqa: PLC0415 -- the wizard drives the CLI that holds it

    return run_setup(
        args.case,
        args.start,
        terminal=interactive(),
        prompter=arrows.prompter,
        call=main,
    )


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "guide": lambda a: run_guide(a.case, a.start),
    "skill": lambda a: run_skill(a, Place.here()),
    "secret": lambda a: run_secret(a, Terminal(interactive(), getpass.getpass, user_variable())),
    "env": lambda a: run_env(a, user_variable()),
    "set": lambda a: run_set(a.config, a.key, a.value),
    "setup": _setup,
}


def add_setup_parsers(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the setup's subcommands."""
    for add in (
        add_guide_parser,
        add_skill_parser,
        add_secret_parser,
        add_env_parser,
        add_set_parser,
        add_setup_parser,
    ):
        add(commands)
