"""The incognito-sql plugin for Claude Code and Codex: the setup skill, installed once.

The repository is the plugins' marketplace: `.claude-plugin/marketplace.json` for Claude
Code and `.agents/plugins/marketplace.json` for Codex point at `plugin/`, which holds
both manifests and the skill of `incognito_sql.setup.skill`, pinned to this version.
The plugin carries no MCP server: the server is set up per project (its database, its
declaration), and the skill has the agent do that through `guide`.

``python -m incognito_sql.setup.plugin`` rewrites the files for the installed version;
a test holds them equal to what it writes.
"""

import json
import sys
from importlib.metadata import version
from pathlib import Path

from incognito_sql.setup.skill import NAME, text

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
        f"{ROOT}/.codex-plugin/plugin.json": _json({**plugin, "skills": "./skills/"}),
        f"{ROOT}/skills/{NAME}/SKILL.md": text(release),
    }


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
