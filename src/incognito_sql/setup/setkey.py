"""`incognito-sql set`: one top-level setting of a declaration, its comments kept.

Only settings a setup step sets: the protection profile and the cards' port. The file must
still load afterwards, or it is left as it was.
"""

import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from incognito_sql.core.config import load_declaration
from incognito_sql.problems import quiet_problem

if TYPE_CHECKING:
    import argparse

EXIT_FAILED = 1
SETTINGS = ("protection", "web_port")
_PLAIN = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def add_set_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the `set` subcommand."""
    cmd = commands.add_parser("set", help="set one top-level setting of a declaration")
    cmd.add_argument("config", type=Path, help="the declaration (YAML)")
    cmd.add_argument("key", choices=SETTINGS)
    cmd.add_argument("value")


def run_set(config: Path, key: str, value: str) -> int:
    """Set ``key`` in ``config``; leave the file as it was if it would not load."""
    if not _PLAIN.fullmatch(value):  # one word: no second line, no comment, no structure
        return _fail(f"{key} takes one word or number")
    try:
        before = config.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(f"cannot read the config ({type(exc).__name__})")
    after = updated(before, key, value)
    try:
        config.write_text(after, encoding="utf-8")
        load_declaration(config)
    except Exception as exc:  # noqa: BLE001 -- file, YAML or schema: any is a bad config
        config.write_text(before, encoding="utf-8")
        return _fail(f"the config is left as it was: {quiet_problem(exc)}")
    sys.stderr.write(f"incognito-sql: {key} set\n")
    return 0


def updated(text: str, key: str, value: str) -> str:
    """Return ``text`` with its top-level ``key:`` line replaced, or the line added."""
    line = f"{key}: {value}"
    pattern = re.compile(rf"^{re.escape(key)}\s*:.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda _: line, text, count=1)
    return text + ("" if text.endswith("\n") or not text else "\n") + line + "\n"


def _fail(message: str) -> int:
    sys.stderr.write(f"incognito-sql: {message}\n")
    return EXIT_FAILED
