"""The three MCP clients of the harness probe: where each is, how its settings are isolated.

Each client reads its settings from a folder an environment variable can move: Claude Code
from ``CLAUDE_CONFIG_DIR``, OpenCode from the four XDG folders, Codex from ``CODEX_HOME``.
The probe points them at a temporary folder, so the owner's own settings are never read
or written.
"""

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

_XDG = ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")
# The binary the VS Code extension ships, when no `claude` is on PATH.
_EXTENSION = ".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude*"


@dataclass(frozen=True)
class Client:
    """One client: its name for ``connect``, its binary, and what the probe asks it."""

    name: str
    binary: Path | None
    connects: bool  # its server list starts each server; Codex's only lists them

    def isolated(self, root: Path) -> dict[str, str]:
        """Return the variables that move this client's settings under ``root``."""
        if self.name == "claude-code":
            config = root / "claude-config"
            config.mkdir(parents=True, exist_ok=True)
            # A project's servers wait for approval on a terminal; the probe has none.
            settings = {"enableAllProjectMcpServers": True}
            (config / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
            return {"CLAUDE_CONFIG_DIR": str(config)}
        if self.name == "opencode":  # it writes data, state and cache too, not only config
            return {var: str(root / "xdg" / var.lower()) for var in _XDG}
        return {"CODEX_HOME": str(root / "codex-home")}

    def owner_files(self, home: Path) -> list[Path]:
        """Return the owner's own settings files, which the probe must leave untouched."""
        if self.name == "claude-code":
            return [home / ".claude.json", home / ".claude" / "settings.json"]
        if self.name == "opencode":
            config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
            return [config / "opencode" / "opencode.json", config / "opencode" / "config.json"]
        codex = Path(os.environ.get("CODEX_HOME") or home / ".codex")
        return [codex / "config.toml"]


def find(home: Path, claude: Path | None = None) -> list[Client]:
    """Return the three clients, each with its binary or None when it is not installed."""
    return [
        Client("claude-code", claude or _which("claude") or _extension(home), connects=True),
        Client("opencode", _which("opencode"), connects=True),
        Client("codex", _which("codex"), connects=False),
    ]


def state(listing: str, server: str) -> str:
    """Return what a client's server list says of ``server``: connected, failed or absent."""
    for line in listing.splitlines():
        if re.search(rf"(^|\W){re.escape(server)}(\W|$)", line):
            low = line.lower()
            if "fail" in low or "error" in low:
                return "failed"
            return "connected" if "connected" in low else "listed"
    return "absent"


def _which(name: str) -> Path | None:
    found = shutil.which(name)
    return Path(found) if found else None


def _extension(home: Path) -> Path | None:
    found = sorted(home.glob(_EXTENSION), key=lambda p: _version(p.parts[-4]))
    return found[-1] if found else None


def _version(folder: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", folder))
