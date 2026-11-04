"""The change case's confirmation: what a new declaration opens, and putting it back."""

import shutil
from pathlib import Path

from incognito_sql.core.config import load_declaration
from incognito_sql.diff.changes import changes
from incognito_sql.diff.kinds import WIDENED
from incognito_sql.setup.model import Answers, fill

YES = "yes"


def widenings(before: Path, after: Path) -> list[str]:
    """Return each WIDENED line of the diff from ``before`` to ``after``."""
    found = changes(load_declaration(before), load_declaration(after))
    return [c.line() for c in found if c.kind == WIDENED]


def put_back_unless_confirmed(answers: Answers) -> None:
    """Restore the config from its copy unless every WIDENED line was confirmed."""
    said = answers.get("widened", [])
    said = [said] if isinstance(said, str) else said
    if any(answer != YES for answer in said):
        shutil.copyfile(fill("{before}", answers), fill("{config}", answers))
