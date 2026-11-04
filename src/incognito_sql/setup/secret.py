"""`incognito-sql secret`: a secret typed by the human, kept where the server reads it.

It reads only from the human's own terminal, with hidden input, and prints only the
variable's name: a token it generates is shown once, to that terminal. Without a terminal
it refuses, so an agent's shell cannot run it.
"""

import base64
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from incognito_sql.connect.clients import valid_variable
from incognito_sql.mcp.token import MIN_TOKEN_CHARS
from incognito_sql.setup.keep import NO_USER_VARIABLE, ForUser, keep

if TYPE_CHECKING:
    import argparse

EXIT_FAILED = 1
EXIT_USAGE = 2
SLOT = "{password}"


@dataclass(frozen=True)
class Terminal:
    """Where the secret comes from and where it goes, for a test to stand in for."""

    present: bool
    hidden: Callable[[str], str]  # getpass
    for_user: ForUser | None  # the OS's user variable; None: none here


def add_secret_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the `secret` subcommand."""
    cmd = commands.add_parser("secret", help="type a secret in your terminal, kept by name")
    cmd.add_argument("name", help="the variable's NAME, e.g. SHOP_DSN")
    cmd.add_argument("--env-file", type=Path, help="keep it in this KEY=VALUE file")
    cmd.add_argument("--template", help="a DSN with {password}: only the password is typed")
    cmd.add_argument("--generate", choices=("key", "token"), help="make it instead of typing it")


def run_secret(args: "argparse.Namespace", terminal: Terminal) -> int:
    """Read or make the secret, keep it, and say only its name."""
    problem = _usage(args, terminal)
    if problem:
        return _fail(problem, EXIT_USAGE)
    if not terminal.present:
        return _fail("secret reads from your own terminal, and there is none here", EXIT_FAILED)
    value = _generated(args.generate) if args.generate else _typed(args.template, terminal)
    if value is None:
        return _fail("nothing was kept: the entries were empty or differ", EXIT_FAILED)
    try:
        where = keep(args.name, value, args.env_file, terminal.for_user)
    except OSError as exc:
        return _fail(f"cannot keep it: {type(exc).__name__}", EXIT_FAILED)
    sys.stderr.write(f"incognito-sql: {args.name} set in {where}\n")
    if args.generate == "token":
        sys.stdout.write(f"{value}\n(shown once: type it into your own client's secret)\n")
    return 0


def _usage(args: "argparse.Namespace", terminal: Terminal) -> str:
    if not valid_variable(args.name):  # a value, perhaps: never repeat it
        return "secret takes a variable's NAME in upper case (e.g. SHOP_DSN)"
    if args.template is not None and (args.generate or args.template.count(SLOT) != 1):
        return f"--template holds {SLOT} once, and goes without --generate"
    if args.env_file is None and terminal.for_user is None:
        return NO_USER_VARIABLE
    return ""


def _typed(template: str | None, terminal: Terminal) -> str | None:
    what = "password" if template else "value"
    first = terminal.hidden(f"{what} (hidden): ")
    if not first or terminal.hidden(f"{what} again: ") != first:
        return None
    return template.replace(SLOT, quote(first, safe="")) if template else first


def _generated(kind: str) -> str:
    if kind == "key":
        return base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    return secrets.token_urlsafe(MIN_TOKEN_CHARS)


def _fail(message: str, code: int) -> int:
    sys.stderr.write(f"incognito-sql: {message}\n")
    return code
