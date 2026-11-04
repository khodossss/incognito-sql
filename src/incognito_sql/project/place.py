"""Where a project keeps its setup: one folder, `.incognito-sql`, in the project's root.

The folder holds the declaration (`config.yaml`), the DSNs that are no secret (`.env`,
`KEY=VALUE`), the token store and audit log next to the declaration, and the demo. A
`.gitignore` of `*` inside keeps all of it out of the project's commits.
"""

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

FOLDER = ".incognito-sql"
# Cards ports a project may take: one per project, picked from its path so two projects
# of the same user rarely meet; a taken one moves on to the next free.
FIRST_PORT, PORTS = 8765, 200


@dataclass(frozen=True)
class Place:
    """One project's setup paths."""

    root: Path

    @classmethod
    def of(cls, env: Mapping[str, str], cwd: Path) -> "Place":
        """Return the project the client names (Claude Code's CLAUDE_PROJECT_DIR), else ``cwd``."""
        named = env.get("CLAUDE_PROJECT_DIR")
        return cls(Path(named) if named else cwd)

    @property
    def folder(self) -> Path:
        """Return the setup folder."""
        return self.root / FOLDER

    @property
    def config(self) -> Path:
        """Return the declaration."""
        return self.folder / "config.yaml"

    @property
    def env_file(self) -> Path:
        """Return the file of DSNs that are no secret (a database file's, the demo's)."""
        return self.folder / ".env"

    @property
    def demo(self) -> Path:
        """Return the demo database."""
        return self.folder / "demo" / "shop.db"

    def prepare(self) -> None:
        """Create the folder with its `.gitignore`, if missing."""
        self.folder.mkdir(parents=True, exist_ok=True)
        ignore = self.folder / ".gitignore"
        if not ignore.exists():
            ignore.write_text("# incognito-sql: tokens, audit and DSNs stay out of commits\n*\n")

    def first_port(self) -> int:
        """Return where this project's search for a cards port starts."""
        digest = hashlib.sha256(os.path.normcase(str(self.root.resolve())).encode()).digest()
        return FIRST_PORT + int.from_bytes(digest[:4], "big") % PORTS
