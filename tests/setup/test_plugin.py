"""The plugin's files in the repository: as `incognito_sql.setup.plugin` writes them."""

import json
from importlib.metadata import version
from pathlib import Path

from incognito_sql.setup.plugin import files, write
from incognito_sql.setup.skill import text

REPO = Path(__file__).parents[2]
RELEASE = version("incognito-sql")


def test_the_repository_holds_the_plugin_of_this_version() -> None:
    for path, content in files(RELEASE).items():
        written = (REPO / path).read_text(encoding="utf-8")
        # Stale after a version change: run `uv run python -m incognito_sql.setup.plugin`.
        assert written == content, path


def test_both_clients_find_the_plugin_and_its_pinned_skill() -> None:
    made = files("9.9.9")
    claude = json.loads(made[".claude-plugin/marketplace.json"])["plugins"][0]
    codex = json.loads(made[".agents/plugins/marketplace.json"])["plugins"][0]
    assert claude["source"] == codex["source"]["path"] == "./plugin"
    assert json.loads(made["plugin/.claude-plugin/plugin.json"])["version"] == "9.9.9"
    assert json.loads(made["plugin/.codex-plugin/plugin.json"])["skills"] == "./skills/"
    assert made["plugin/skills/incognito-sql/SKILL.md"] == text("9.9.9")


def test_write_lays_out_every_file(tmp_path: Path) -> None:
    write(tmp_path, "9.9.9")
    assert {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()} == set(
        files("9.9.9")
    )
