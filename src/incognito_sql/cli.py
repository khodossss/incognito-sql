"""The `incognito-sql` command line: `_parser` lists the commands, `main` runs one."""

import argparse
import logging
import os
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from incognito_sql.assess.command import add_assess_parser, run_assess
from incognito_sql.audit_command import add_audit_parser, run_audit
from incognito_sql.check.run import run_check
from incognito_sql.connect.clients import valid_variable
from incognito_sql.connect.run import Where, add_connect_parser, run_connect
from incognito_sql.core.budget import SESSIONLESS
from incognito_sql.core.config import Declaration, load_declaration
from incognito_sql.core.tokens.crypto import load_key
from incognito_sql.demo import add_demo_parser, run_demo
from incognito_sql.diff.run import add_diff_parser, run_diff
from incognito_sql.dpo.command import add_report_parser, run_report
from incognito_sql.envfile import EnvFileError, load_env_file
from incognito_sql.init.run import add_init_parser, run_init
from incognito_sql.mcp.token import TokenError, service_token
from incognito_sql.parser import QuietParser
from incognito_sql.problems import quiet_problem
from incognito_sql.project.run import add_project_parser, run_project
from incognito_sql.serving import (
    EXIT_FAILED,
    EXIT_USAGE,
    StartError,
    cards_socket,
    http_run,
    opened,
    serve,
)
from incognito_sql.setup.commands import COMMANDS as SETUP_COMMANDS
from incognito_sql.setup.commands import add_setup_parsers
from incognito_sql.trial.run import add_try_parser, run_try
from incognito_sql.web.run import HOST, LocalWeb
from incognito_sql.wiring import open_cards, open_gateway, token_domain

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer  # noqa: TID251 -- typing only, never at runtime

__all__ = ["StartError", "main", "open_cards", "open_gateway", "token_domain"]


def main(argv: list[str] | None = None) -> int:
    """Run the command line; return the process exit code."""
    args = _parser().parse_args(argv)
    _quiet_logging()
    return _COMMANDS.get(args.command, _run)(args)


def _connect(args: argparse.Namespace) -> int:
    codex_home = os.environ.get("CODEX_HOME")
    where = Where(Path.home(), Path.cwd(), codex_home, sys.stdin.isatty(), input)
    return run_connect(args, where)


def _assess(args: argparse.Namespace) -> int:
    try:
        if args.env_file is not None:
            _load_env(args.env_file)
        settings = _settings(args.config)
    except StartError as exc:
        sys.stderr.write(f"incognito-sql: {exc}\n")
        return exc.code
    return run_assess(args, *settings)


_COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {  # the rest serve: `_run`
    "init": lambda a: run_init(
        a.dsn_env, a.dialect, a.out, use_sample=not a.no_sample, env_file=a.env_file
    ),
    "check": lambda a: run_check(a.config, a.env_file, a.database),
    "connect": _connect,
    "demo": lambda a: run_demo(a.folder),
    "try": lambda a: run_try(a.config, a.env_file, a.sql),
    "diff": lambda a: run_diff(a.old, a.new, ci=a.ci),
    "assess": _assess,
    "report": run_report,
    "audit": run_audit,
    "project": lambda _a: run_project(),
}
_COMMANDS |= SETUP_COMMANDS


def _run(args: argparse.Namespace) -> int:
    """Start `serve`, `service`, `web` or `login` with the config's settings."""
    try:
        if args.env_file is not None:
            _load_env(args.env_file)
        decl, dsn, key = _settings(args.config)
        if args.command == "serve":  # one stdio process = one connection
            return serve(args.config, decl, dsn, key, _run_stdio, uuid4().hex)
        if args.command == "service":
            run = _run_http(decl.mcp_port, _token())
            sys.stderr.write(f"incognito-sql: MCP on http://{HOST}:{decl.mcp_port}/mcp\n")
            return serve(args.config, decl, dsn, key, run, SESSIONLESS, cards_required=True)
        sock = cards_socket(decl, required=args.command == "web")
        parts = opened(lambda: open_cards(args.config, decl, dsn, key), sock)
    except StartError as exc:
        sys.stderr.write(f"incognito-sql: {exc}\n")
        return exc.code
    if args.command == "login":
        url = f"http://{HOST}:{decl.web_port}/login/{parts.sessions.issue_code()}"
        _login(url, print_only=args.print)
    if sock is None:  # the web that holds the port exchanges the code
        parts.close()
        return 0
    sys.stderr.write(f"incognito-sql: cards on http://{HOST}:{decl.web_port}/ (Ctrl+C stops)\n")
    return 0 if LocalWeb(parts, sock).run() else EXIT_FAILED


def _login(url: str, *, print_only: bool) -> None:
    # Printed for an administrator's run: the link is opened in the human's own browser.
    if print_only:
        sys.stdout.write(f"{url}\n")
        sys.stdout.flush()  # the web runs on: a pipe would hold the link until it stops
    elif not webbrowser.open(url):
        sys.stderr.write(f"incognito-sql: open {url}\n")


def _load_env(path: Path) -> None:
    try:
        load_env_file(path, os.environ)
    except EnvFileError as exc:
        raise StartError(str(exc), EXIT_USAGE) from None


def _token() -> str:
    try:
        return service_token(os.environ)
    except TokenError as exc:
        raise StartError(str(exc), EXIT_USAGE) from None


def _settings(config: Path) -> tuple[Declaration, str, bytes]:
    try:
        decl = load_declaration(config)
    except Exception as exc:  # noqa: BLE001 -- file, YAML or schema: any is a bad config
        msg = f"cannot read the config: {quiet_problem(exc)}"
        raise StartError(msg) from None
    if not valid_variable(decl.dsn_env):  # a DSN or a token, perhaps: never repeat it
        msg = "the config's dsn_env must be a variable's NAME in upper case (e.g. SHOP_DSN)"
        raise StartError(msg, EXIT_USAGE)
    dsn = os.environ.get(decl.dsn_env)
    if not dsn:
        msg = f"environment variable {decl.dsn_env} is not set"
        raise StartError(msg, EXIT_USAGE)
    try:
        key = load_key()
    except (RuntimeError, ValueError) as exc:  # fixed messages, no key material
        raise StartError(str(exc)) from None
    return decl, dsn, key


def _parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = QuietParser(prog="incognito-sql")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("serve", "run the MCP server over stdio, and the cards if their port is free"),
        ("service", "run the MCP server over HTTP on 127.0.0.1 behind a token, and the cards"),
        ("web", "serve the cards in the foreground"),
        ("login", "issue a one-time sign-in link and open it in the browser"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("--config", type=Path, required=True, help="field declaration (YAML)")
        command.add_argument("--env-file", type=Path, help="KEY=VALUE secrets for unset variables")
        if name == "login":
            command.add_argument("--print", action="store_true", help="print the link instead")
    check = commands.add_parser("check", help="try what an agent running as this user could reach")
    check.add_argument("--config", type=Path, help="the service's field declaration")
    check.add_argument("--env-file", type=Path, help="the service's secrets file (only probed)")
    check.add_argument("--database", type=Path, help="a SQLite or DuckDB file (only probed)")
    add_init_parser(commands)
    add_connect_parser(commands)
    add_demo_parser(commands)
    add_try_parser(commands)
    add_diff_parser(commands)
    add_assess_parser(commands)
    add_report_parser(commands)
    add_audit_parser(commands)
    add_project_parser(commands)
    add_setup_parsers(commands)
    return parser


def _quiet_logging() -> None:
    # stderr carries nothing below WARNING: debug records may hold raw driver text.
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    logging.getLogger("incognito_sql").setLevel(logging.WARNING)


def _run_stdio(server: "MCPServer") -> None:
    server.run("stdio")


def _run_http(port: int, token: str) -> Callable[["MCPServer"], None]:
    return http_run(port, token)
