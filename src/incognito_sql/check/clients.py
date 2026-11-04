"""MCP client settings this user can read, and the entries that start incognito-sql itself."""

import json
import re
import tomllib
from collections.abc import Iterator, Mapping
from pathlib import Path

from incognito_sql.check.probes import Finding

_NAMES = ("incognito-sql", "incognito_sql")
# A value that only names a variable the client fills in: `${env:X}`, `{env:X}`, `${X}`.
_REFERENCE = re.compile(r"\$?\{(?:env:)?[A-Za-z_][A-Za-z0-9_]*\}")


def client_settings(home: Path, cwd: Path, environ: Mapping[str, str]) -> list[tuple[str, Path]]:
    """Return the MCP settings files of common clients, each with a fixed label.

    A finding names the file by its label: a path built from a variable such as
    CODEX_HOME may hold anything pasted there, and is not repeated.
    """
    codex = environ.get("CODEX_HOME")
    files = [
        ("Claude Code project file (.mcp.json)", cwd / ".mcp.json"),
        ("Cursor project file (.cursor/mcp.json)", cwd / ".cursor" / "mcp.json"),
        ("OpenCode project file (opencode.json)", cwd / "opencode.json"),
        ("Claude Code user file (~/.claude.json)", home / ".claude.json"),
        ("Cursor user file (~/.cursor/mcp.json)", home / ".cursor" / "mcp.json"),
        (
            "OpenCode user file (~/.config/opencode/opencode.json)",
            home / ".config" / "opencode" / "opencode.json",
        ),
        ("Codex user file (~/.codex/config.toml)", home / ".codex" / "config.toml"),
        (
            "Claude Desktop file (macOS)",
            home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        ),
        ("Claude Desktop file (Linux)", home / ".config" / "Claude" / "claude_desktop_config.json"),
    ]
    if codex:
        files.append(("Codex file ($CODEX_HOME/config.toml)", Path(codex) / "config.toml"))
    if "APPDATA" in environ:
        path = Path(environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
        files.append(("Claude Desktop file (Windows)", path))
    return files


def _servers(tree: object) -> Iterator[Mapping[str, object]]:
    """Yield every server entry at any depth.

    The keys are `mcpServers` (Claude Code nests them per project; Cursor),
    `mcp_servers` (Codex) and `mcp` (OpenCode).
    """
    if isinstance(tree, dict):
        for key in ("mcpServers", "mcp_servers", "mcp"):
            servers = tree.get(key)
            if isinstance(servers, dict):
                yield from (s for s in servers.values() if isinstance(s, dict))
        for value in tree.values():
            yield from _servers(value)
    elif isinstance(tree, list):
        for value in tree:
            yield from _servers(value)


def _starts_us(server: Mapping[str, object]) -> bool:
    command = server.get("command", "")
    words = list(command) if isinstance(command, list) else [command]  # OpenCode: a list
    args = server.get("args", [])
    if isinstance(args, list):
        words.extend(args)
    # The script name, or the package run as a module (`python -m incognito_sql`).
    return any(name in str(word) for word in words for name in _NAMES)


def _parsed(path: Path) -> object:
    text = path.read_text(encoding="utf-8-sig")
    return tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)


def client_findings(files: list[tuple[str, Path]]) -> list[Finding]:
    """Flag each client entry that runs incognito-sql as this user, with secrets beside it."""
    found: list[Finding] = []
    for label, path in files:
        try:
            servers = list(_servers(_parsed(path)))
        except (OSError, ValueError, RecursionError):  # unreadable, not JSON or TOML, too deep
            continue
        for server in servers:
            if not _starts_us(server):
                continue
            env = server.get("env", server.get("environment"))  # OpenCode: `environment`
            what = f"{label} starts incognito-sql as this user"
            if isinstance(env, dict) and any(
                not _REFERENCE.fullmatch(str(value)) for value in env.values()
            ):
                what += ", with its secrets in the file"
            found.append(Finding(what, hole=True, fix="run it as a service and connect over HTTP"))
    return found
