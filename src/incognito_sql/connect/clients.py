"""The entry each MCP client needs, in its own format.

A server reaches a client in one of two ways: the client starts `incognito-sql serve`
over stdio (the convenient installation profile), or it calls the service at a URL with
a bearer token (the closed one). Either way the entry names environment variables, in
the client's own substitution syntax, and never holds a DSN, key or token value.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from incognito_sql import shell
from incognito_sql.core.tokens.crypto import ENV_KEY

CLIENTS = ("claude-code", "codex", "cursor", "opencode")
TOKEN_ENV = "INCOGNITO_SQL_MCP_TOKEN"  # noqa: S105 -- a variable name, not a secret
# The extra of each dialect's driver (pyproject); SQLite needs none.
DRIVERS = {"postgres": "postgres", "mysql": "mysql", "tsql": "mssql", "duckdb": "duckdb"}
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# A variable's name, never a secret pasted in its place: upper case, shorter than the 32
# characters a service token needs (mcp/token.py), and a long name has a word break.
# A DSN has `:`; a random token (hex, url-safe, `ghp_...`, base32) has lower case
# letters or no underscore.
_VARIABLE = re.compile(r"^(?=.{1,15}$|.*_)[A-Z_][A-Z0-9_]{0,30}$")


@dataclass(frozen=True)
class Server:
    """incognito-sql as a client sees it: a command over stdio, or a URL with a token."""

    name: str
    command: tuple[str, ...] = ()
    env: tuple[str, ...] = ()  # variable names the command needs, never their values
    url: str = ""
    token_env: str = ""


def valid_name(name: str) -> bool:
    """Tell whether ``name`` can key a server in every client's settings."""
    return bool(_NAME.fullmatch(name))


def valid_variable(name: str) -> bool:
    """Tell whether ``name`` names a variable and cannot be a DSN or a token itself."""
    return bool(_VARIABLE.fullmatch(name))


def stdio(  # noqa: PLR0913 -- the server, then which installation runs it
    name: str,
    config: Path,
    dsn_env: str,
    dialect: str,
    *,
    release: str | None,
    python: str,
    env_file: Path | None = None,
) -> Server:
    """Return the server the client starts itself: the pinned ``release`` through uvx.

    Without a release (a checkout, a development build) the entry runs this installation:
    ``python -m incognito_sql``, by the interpreter's absolute path. With ``env_file`` the
    server reads the DSN from that file, and the entry passes no variable for it.
    """
    serve: tuple[str, ...] = ("serve", "--config", str(config.resolve()))
    if env_file is not None:
        serve += ("--env-file", str(env_file.resolve()))
    env = () if env_file is not None else (dsn_env,)
    if release is None:
        return Server(name, (python, "-m", "incognito_sql", *serve), env)
    extras = ",".join(["mcp", *([DRIVERS[dialect]] if dialect in DRIVERS else [])])
    pinned = f"incognito-sql[{extras}]=={release}"
    return Server(name, ("uvx", "--from", pinned, "incognito-sql", *serve), env)


def http(name: str, url: str, token_env: str = TOKEN_ENV) -> Server:
    """Return the service at ``url``, its bearer token read from ``token_env``."""
    return Server(name, url=url, token_env=token_env)


def claude_code(server: Server) -> str:
    """Return the `claude mcp add` command: Claude Code writes its own settings."""
    line = ["claude", "mcp", "add", "--scope", "project"]
    if server.url:
        bearer = f"Authorization: Bearer ${{{server.token_env}}}"
        line += ["--transport", "http", server.name, server.url, "-H", bearer]
    else:
        # The name comes first: `-e` takes every word up to the `--`.
        line.append(server.name)
        for var in server.env:
            line += ["-e", f"{var}=${{{var}}}"]
        line += ["--", *server.command]
    return shell.join(line)


def codex(server: Server) -> str:
    """Return the `[mcp_servers.<name>]` table of Codex's `config.toml`."""
    lines = [f"[mcp_servers.{server.name}]"]
    if server.url:
        lines += [f"url = {_toml(server.url)}", f"bearer_token_env_var = {_toml(server.token_env)}"]
    else:
        command, *args = server.command
        lines += [f"command = {_toml(command)}", f"args = [{', '.join(map(_toml, args))}]"]
        # Codex passes on only the variables listed, and only those that are set.
        lines += [f"env_vars = [{', '.join(map(_toml, (*server.env, ENV_KEY)))}]"]
    return "\n".join(lines) + "\n"


def cursor(server: Server) -> dict[str, object]:
    """Return the entry under `mcpServers` in Cursor's `mcp.json`."""
    if server.url:
        return {"url": server.url, "headers": _bearer(f"${{env:{server.token_env}}}")}
    command, *args = server.command
    env = {var: f"${{env:{var}}}" for var in server.env}
    return {"command": command, "args": args, "env": env}


def opencode(server: Server) -> dict[str, object]:
    """Return the entry under `mcp` in OpenCode's `opencode.json`."""
    if server.url:
        headers = _bearer(f"{{env:{server.token_env}}}")
        return {"type": "remote", "url": server.url, "headers": headers, "oauth": False}
    environment = {var: f"{{env:{var}}}" for var in server.env}
    return {"type": "local", "command": list(server.command), "environment": environment}


def block(client: str, server: Server) -> str:
    """Return what to paste into ``client``'s settings, or to run for Claude Code."""
    if client == "claude-code":
        return claude_code(server) + "\n"
    if client == "codex":
        return codex(server)
    key, entry = ("mcpServers", cursor(server)) if client == "cursor" else ("mcp", opencode(server))
    return json.dumps({key: {server.name: entry}}, indent=2, ensure_ascii=False) + "\n"


def _toml(text: str) -> str:
    return json.dumps(text)  # a JSON string is a TOML basic string


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
