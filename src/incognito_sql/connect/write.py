"""Adding a server to a client's settings file, only after a yes on a terminal.

Only Codex, Cursor and OpenCode are written here (Claude Code writes its own settings
from `claude mcp add`). Nothing of the file is read before the terminal is known, and
nothing of it is printed: the operator sees only the entry being added, since the file
may hold other servers' secrets. A server of the same name, a file that is not plain
JSON or TOML, or a result that would not parse is a refusal; the rest of the file keeps
its data.
"""

import json
import tomllib
from collections.abc import Callable
from pathlib import Path

from incognito_sql.connect.clients import Server, codex, cursor, opencode

WRITABLE = ("codex", "cursor", "opencode")


class WriteRefused(Exception):  # noqa: N818 -- a refusal, said to the operator as is
    """The settings file is left as it was; the message says why."""


def default_file(client: str, home: Path, cwd: Path, codex_home: str | None) -> Path:
    """Return the settings file a client reads: Codex's user file, the others' project file."""
    if client == "codex":
        return Path(codex_home) / "config.toml" if codex_home else home / ".codex" / "config.toml"
    if client == "cursor":
        return cwd / ".cursor" / "mcp.json"
    return cwd / "opencode.json"


def read(path: Path) -> str:
    """Return the settings file's text, empty if there is none; raise WriteRefused if unreadable."""
    try:
        return path.read_text(encoding="utf-8-sig") if path.exists() else ""
    except UnicodeDecodeError:
        msg = "the file is not UTF-8: add the entry by hand"
        raise WriteRefused(msg) from None


def updated(client: str, server: Server, current: str) -> str:
    """Return the file's text with ``server`` added; raise WriteRefused if it cannot be."""
    if client == "codex":
        after = _toml_added(server, current)
    else:
        pair = ("mcpServers", cursor(server)) if client == "cursor" else ("mcp", opencode(server))
        after = _json_added(pair[0], server.name, pair[1], current)
    try:  # checked before the file is opened for writing, which would empty it
        after.encode("utf-8")
    except UnicodeEncodeError:  # e.g. a lone surrogate escaped in the JSON
        msg = "the file holds text that cannot be written back: add the entry by hand"
        raise WriteRefused(msg) from None
    return after


def write(path: Path, after: str, *, ask: Callable[[str], str], shown: str = "") -> None:
    """Write ``after`` to ``path`` once the operator answers yes; raise WriteRefused if not.

    The question names the file as ``shown``, or by its path.
    """
    try:
        answer = ask(f"Add it to {shown or path} (the rest of the file is kept)? [y/N] ")
    except EOFError:  # Windows reads NUL as a terminal that answers nothing
        answer = ""
    if answer.strip().casefold() not in {"y", "yes"}:
        msg = "the file is left as it was"
        raise WriteRefused(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(after, encoding="utf-8")


def _json_added(key: str, name: str, entry: dict[str, object], current: str) -> str:
    try:
        data = json.loads(current) if current.strip() else {}
    except (ValueError, RecursionError):  # bad JSON, a huge number, deep nesting
        msg = "the file is not plain JSON (comments?): add the entry by hand"
        raise WriteRefused(msg) from None
    servers = data.get(key, {}) if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        msg = f"the file's `{key}` is not an object: add the entry by hand"
        raise WriteRefused(msg)
    if name in servers:
        msg = f"a server named {name} is already there: pick another --name"
        raise WriteRefused(msg)
    try:
        text = json.dumps(
            {**data, key: {**servers, name: entry}}, indent=2, ensure_ascii=False, allow_nan=False
        )
    except ValueError:  # a number too large for a float would come back as Infinity
        msg = "the file holds a number that cannot be written back: add the entry by hand"
        raise WriteRefused(msg) from None
    return text + ("" if current and not current.endswith("\n") else "\n")


def _toml_added(server: Server, current: str) -> str:
    try:
        servers = tomllib.loads(current).get("mcp_servers", {})
    except tomllib.TOMLDecodeError:
        msg = "the file is not valid TOML: add the entry by hand"
        raise WriteRefused(msg) from None
    if not isinstance(servers, dict):
        msg = "the file's `mcp_servers` is not a table: add the entry by hand"
        raise WriteRefused(msg)
    if server.name in servers:
        msg = f"a server named {server.name} is already there: pick another --name"
        raise WriteRefused(msg)
    gap = (
        ""
        if not current or current.endswith("\n\n")
        else "\n"
        if current.endswith("\n")
        else "\n\n"
    )
    after = current + gap + codex(server)
    try:
        tomllib.loads(after)
    except tomllib.TOMLDecodeError:  # e.g. `mcp_servers` written as an inline table
        msg = "the entry cannot be appended to this file's layout: add it by hand"
        raise WriteRefused(msg) from None
    return after
