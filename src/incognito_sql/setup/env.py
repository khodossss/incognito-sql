"""`incognito-sql env`: a variable that is no secret (a demo's DSN, a database file's path).

It is kept where `secret` keeps one, for the user or in an env file; a secret goes through
`secret`, typed hidden in the human's terminal.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from incognito_sql.connect.clients import valid_variable
from incognito_sql.setup.keep import NO_USER_VARIABLE, ForUser, keep
from incognito_sql.setup.model import FILE_DIALECTS

if TYPE_CHECKING:
    import argparse

EXIT_FAILED = 1
EXIT_USAGE = 2


def add_env_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the `env` subcommand."""
    cmd = commands.add_parser("env", help="keep a variable that is no secret, by name")
    cmd.add_argument("name", help="the variable's NAME, e.g. DEMO_SHOP_DSN")
    cmd.add_argument("value", nargs="?", help="its value (or --file)")
    cmd.add_argument("--file", type=Path, help="a database file: the value is its DSN")
    cmd.add_argument("--dialect", choices=FILE_DIALECTS, default="sqlite", help="with --file")
    cmd.add_argument("--env-file", type=Path, help="keep it in this KEY=VALUE file")


def run_env(args: "argparse.Namespace", for_user: ForUser | None) -> int:
    """Keep the variable; say only its name."""
    if not valid_variable(args.name):
        return _fail("env takes a variable's NAME in upper case (e.g. SHOP_DSN)", EXIT_USAGE)
    if (args.value is None) == (args.file is None):
        return _fail("env takes a value or --file, one of them", EXIT_USAGE)
    if args.env_file is None and for_user is None:
        return _fail(NO_USER_VARIABLE, EXIT_USAGE)
    value = args.value
    if args.file is not None:
        value = f"{args.dialect}:///{args.file.resolve().as_posix()}"
    try:
        where = keep(args.name, value, args.env_file, for_user)
    except OSError as exc:
        return _fail(f"cannot keep it: {type(exc).__name__}", EXIT_FAILED)
    sys.stderr.write(f"incognito-sql: {args.name} set in {where}\n")
    return 0


def _fail(message: str, code: int) -> int:
    sys.stderr.write(f"incognito-sql: {message}\n")
    return code
