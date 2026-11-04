"""The incognito-sql plugin for Claude Code and Codex: the project server and its skill.

The repository is the plugins' marketplace: `.claude-plugin/marketplace.json` for Claude
Code and `.agents/plugins/marketplace.json` for Codex point at `plugin/`, which holds
both manifests, the MCP entry `.mcp.json` and the skill of `incognito_sql.setup.skill`,
all pinned to this version. The client starts `incognito-sql project` in every project:
the server finds the project's own setup there, and its tools make it.

``python -m incognito_sql.setup.plugin`` rewrites the files for the installed version;
a test holds them equal to what it writes.
"""

import json
import sys
from importlib.metadata import version
from pathlib import Path

from incognito_sql.setup.guide import RULE
from incognito_sql.setup.skill import NAME

DESCRIPTION = (
    "Set up incognito-sql: the agent connects a database through an MCP server and queries "
    "it without receiving the personal data in it."
)
AUTHOR = {"name": "khodossss", "url": "https://github.com/khodossss"}
REPOSITORY = "https://github.com/khodossss/incognito-sql"
ROOT = "plugin"


def files(release: str) -> dict[str, str]:
    """Return the plugin's and the marketplaces' files by their path in the repository."""
    plugin = {
        "name": NAME,
        "version": release,
        "description": DESCRIPTION,
        "author": AUTHOR,
        "repository": REPOSITORY,
        "license": "Apache-2.0",
    }
    claude_market = {
        "name": NAME,
        "owner": {"name": AUTHOR["name"]},
        "plugins": [
            {"name": NAME, "source": f"./{ROOT}", "description": DESCRIPTION, "version": release}
        ],
    }
    codex_market = {
        "name": NAME,
        "interface": {"displayName": NAME},
        "plugins": [
            {
                "name": NAME,
                "source": {"source": "local", "path": f"./{ROOT}"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
                "category": "Developer Tools",
            }
        ],
    }
    return {
        ".claude-plugin/marketplace.json": _json(claude_market),
        ".agents/plugins/marketplace.json": _json(codex_market),
        f"{ROOT}/.claude-plugin/plugin.json": _json(plugin),
        f"{ROOT}/.codex-plugin/plugin.json": _json(
            {**plugin, "skills": "./skills/", "mcpServers": "./.mcp.json"}
        ),
        f"{ROOT}/.mcp.json": _json(server(release)),
        f"{ROOT}/skills/{NAME}/SKILL.md": plugin_text(release),
    }


def server(release: str) -> dict[str, object]:
    """Return the MCP entry the client starts in every project: this release's server."""
    command = {
        "command": "uvx",
        "args": ["--from", f"incognito-sql[mcp]=={release}", NAME, "project"],
    }
    return {"mcpServers": {NAME: command}}


def plugin_text(version: str) -> str:
    """Return the plugin's skill: the setup through the project server's tools."""
    run = f'uvx "incognito-sql=={version}"'
    return f"""---
name: {NAME}
description: Set up and use incognito-sql, the MCP server through which an agent queries a \
database holding personal data without receiving the values. Use when the user asks to \
connect a database through incognito-sql, to try its demo, to query such a database, to \
hide personal data from the agent while it writes SQL, or to change what incognito-sql hides.
---

# incognito-sql in this project

This plugin runs the incognito-sql server in every project. Its tools do the setup:
`setup_status`, `create_demo`, `draft_declaration`, `open_cards`, then `describe` and
`query`. Nothing is installed or run in a terminal, except the password, which is the
human's. No step needs a client restart.

1. Call `setup_status` first, and again after every step. It says what is set up and the
   next step; follow it.
2. The demo: `create_demo`, then `describe` and `query` (ask who spent the most).
3. The human's database in a file (SQLite, DuckDB): `draft_declaration` with `dialect` and
   `database_file`. On a server: ask the dialect and a variable name such as SHOP_DSN; the
   human runs, in their own terminal, the `secret` command `setup_status` prints; then
   `draft_declaration` with `dialect` and `dsn_env`.
4. Go through the draft with the human, column by column. Each column gets a class:
   `identifier` (you get a token, the human the value on a card), `open` (both the
   value), `open_quasi` (both the value; may identify in combination), `closed` (you
   nothing, the human the value on a card), `closed_hidden` (nobody). Ask, too, which
   table holds people and its key (`entities`), and the protection profile: `strict` for
   health, finance or strict audit, `balanced` for a CRM or orders, `permissive` for own
   or test data. Write all of it into `.incognito-sql/config.yaml`; then `setup_status`.
5. Query only through `describe` and `query`. Never open the database file or
   `.incognito-sql/.env`, never connect with a driver or a script of your own.
6. If a tool call or a command is refused or blocked, stop and tell the human what was
   refused and what they can allow. Never work around it.
7. Once an answer holds links, offer the human to see the real values; on their yes,
   call `open_cards`: it signs them in on their own browser.
8. Other people's personal data is the closed setup, a service under another OS user,
   which this server does not run: its steps are `{run} guide --case closed`.

{RULE}"""


def _json(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write(root: Path, release: str) -> None:
    """Write the files under ``root``, the repository."""
    for path, content in files(release).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write(Path.cwd(), version(NAME))
    sys.stderr.write(f"incognito-sql: plugin files written for {version(NAME)}\n")
