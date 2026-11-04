"""The `connect` command: print a client's entry for this server, and add it on a yes."""

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from incognito_sql import shell
from incognito_sql.connect.clients import (
    CLIENTS,
    TOKEN_ENV,
    Server,
    block,
    http,
    stdio,
    valid_name,
    valid_variable,
)
from incognito_sql.connect.release import release
from incognito_sql.connect.write import WRITABLE, WriteRefused, default_file, read, updated, write
from incognito_sql.core.config import load_declaration
from incognito_sql.problems import quiet_problem

if TYPE_CHECKING:
    import argparse

EXIT_FAILED = 1
EXIT_USAGE = 2


@dataclass(frozen=True)
class Where:
    """What `connect` reads besides its arguments: the places and the operator's terminal."""

    home: Path
    cwd: Path
    codex_home: str | None
    terminal: bool
    ask: Callable[[str], str]


def add_connect_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the `connect` subcommand."""
    connect = commands.add_parser("connect", help="print an MCP client's entry for this server")
    connect.add_argument("client", choices=CLIENTS)
    source = connect.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path, help="the client starts `serve` with this config")
    source.add_argument("--url", help="the client calls the service at this URL (closed profile)")
    connect.add_argument("--name", help="the server's name in the client (default: config stem)")
    connect.add_argument("--token-env", default=TOKEN_ENV, help="the token variable's NAME")
    connect.add_argument("--write", action="store_true", help="add it to the client's settings")
    connect.add_argument("--file", type=Path, help="the settings file to write (with --write)")
    connect.add_argument(
        "--env-file", type=Path, help="with --config: the server reads its DSN from this file"
    )
    connect.add_argument(
        "--yes", action="store_true", help="with --write: write without asking, no terminal needed"
    )


def run_connect(args: "argparse.Namespace", where: Where) -> int:
    """Print the entry; with ``--write``, add it to the settings file after a yes."""
    if args.yes and not args.write:
        return _fail("--yes goes with --write", EXIT_USAGE)
    try:
        server = _server(args)
    except ValueError as exc:
        return _fail(str(exc), EXIT_USAGE)
    sys.stdout.write(block(args.client, server))
    _advise(args, server)
    return _write(args, server, where) if args.write else 0


def _write(args: "argparse.Namespace", server: Server, where: Where) -> int:
    if args.client not in WRITABLE:
        return _fail("Claude Code writes its own settings: run the command above", EXIT_USAGE)
    if not (args.yes or where.terminal):  # before the file is read: it may hold secrets
        return _fail("--write asks before it writes, and there is no terminal", EXIT_FAILED)
    path = args.file or default_file(args.client, where.home, where.cwd, where.codex_home)
    # A path built from CODEX_HOME may hold anything pasted there: it goes by its name.
    from_env = args.file is None and args.client == "codex" and bool(where.codex_home)
    shown = "the Codex config (from CODEX_HOME)" if from_env else str(path)
    try:
        after = updated(args.client, server, read(path))
        write(path, after, ask=(lambda _: "y") if args.yes else where.ask, shown=shown)
    except WriteRefused as exc:
        return _fail(str(exc), EXIT_FAILED)
    except OSError as exc:
        return _fail(f"cannot write the client's file: {type(exc).__name__}", EXIT_FAILED)
    sys.stderr.write(f"incognito-sql: added {server.name} to {shown}\n")
    return 0


def _server(args: "argparse.Namespace") -> Server:
    if not valid_variable(args.token_env):  # never repeat it: it may be the token
        msg = "--token-env takes a variable's NAME in upper case (e.g. SHOP_MCP_TOKEN)"
        raise ValueError(msg)
    if args.url is not None:
        if args.env_file is not None:
            msg = "--env-file goes with --config: the service holds its own secrets"
            raise ValueError(msg)
        _check_url(args.url)
        server = http(args.name or "incognito-sql", args.url, args.token_env)
    else:
        try:
            decl = load_declaration(args.config)
        except Exception as exc:  # noqa: BLE001 -- file, YAML or schema: any is a bad config
            msg = f"cannot read the config: {quiet_problem(exc)}"
            raise ValueError(msg) from None
        if not valid_variable(decl.dsn_env):  # a DSN or a token, perhaps: never repeat it
            msg = "the config's dsn_env must be a variable's NAME in upper case (e.g. SHOP_DSN)"
            raise ValueError(msg)
        name = args.name or args.config.stem
        server = stdio(
            name,
            args.config,
            decl.dsn_env,
            decl.dialect,
            release=release(),
            python=sys.executable,
            env_file=args.env_file,
        )
    if not valid_name(server.name):
        msg = "the server's name takes letters, digits, - and _ (--name)"
        raise ValueError(msg)
    return server


def _check_url(url: str) -> None:
    msg = "--url takes the service's http(s) address"
    try:  # urllib's own message quotes the address: never pass it on
        parts = urlsplit(url)
        host, _port = parts.hostname, parts.port
    except ValueError:
        raise ValueError(msg) from None
    if parts.scheme not in {"http", "https"} or not host:
        raise ValueError(msg)
    if "@" in url or parts.username or parts.password or parts.query or parts.fragment:
        msg = "--url must hold no user, password or query: the token goes in --token-env"
        raise ValueError(msg)


def _advise(args: "argparse.Namespace", server: Server) -> None:
    say = sys.stderr.write
    if server.url:
        say(f"incognito-sql: set {server.token_env} to the service's token where the client runs\n")
    else:
        where = (
            f"set {server.env[0]} where the client starts; the entry names it"
            if server.env
            else "the server reads its DSN from the --env-file"
        )
        say(
            f"incognito-sql: {where}. "
            "The client starts the server as the agent's own user (the convenient profile): "
            "for other people's data run the service and connect with --url "
            "(docs/deployment.md)\n"
        )
        if server.command[0] != "uvx":
            say(
                "incognito-sql: this installation is no published release: the entry runs it "
                "by its own interpreter, so keep it where it is\n"
            )
    config = f" --config {shell.quote(str(args.config))}" if args.config else ""
    say(f"incognito-sql: then, as the agent's account: incognito-sql check{config}\n")


def _fail(message: str, code: int) -> int:
    sys.stderr.write(f"incognito-sql: {message}\n")
    return code
