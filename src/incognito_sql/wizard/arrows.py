"""Choices drawn with arrow keys (questionary), and the fall back to numbers where they are not.

The wizard asks with arrows by default. A console that cannot draw them (Git Bash under
mintty, an output that is no terminal) gets the numbered prompter, and is told so.
"""

import sys
from collections.abc import Callable, Sequence
from typing import Any

import questionary
from prompt_toolkit.output import create_output

from incognito_sql.wizard.prompts import LinePrompter, Prompter

NO_ARROWS = "This console cannot draw arrow-key choices: answer with numbers."
_REFUSED = "this answer is not accepted here"


class ArrowPrompter:
    """A prompter that draws lists to move through with arrow keys and pick with Enter."""

    def __init__(self, write: Callable[[str], object], **io: Any) -> None:  # noqa: ANN401
        """Show lines with ``write``; ``io`` (prompt_toolkit's input, output) is for tests."""
        self._write = write
        self._io = io

    def tell(self, text: str) -> None:
        """Show a line of text."""
        self._write(text + "\n")

    def one(self, text: str, options: Sequence[str], default: str | None) -> str:
        """Pick one option with the arrow keys."""
        pick = default if default in options else None
        answer: str = questionary.select(text, list(options), default=pick, **self._io).unsafe_ask()
        return answer

    def many(self, text: str, options: Sequence[str], chosen: Sequence[str]) -> list[str]:
        """Tick options with the space bar; ``chosen`` start ticked."""
        choices = [questionary.Choice(o, checked=o in chosen) for o in options]
        answer: list[str] = questionary.checkbox(text, choices, **self._io).unsafe_ask()
        return answer

    def yesno(self, text: str, *, default: bool) -> bool:
        """Answer y or n; Enter takes ``default``."""
        answer: bool = questionary.confirm(text, default=default, **self._io).unsafe_ask()
        return answer

    def text(self, text: str, default: str | None, valid: Callable[[str], bool] | None) -> str:
        """Type a line; one that ``valid`` refuses is not taken."""

        def check(answer: str) -> bool | str:
            return (bool(answer) and (valid is None or valid(answer))) or _REFUSED

        answer: str = questionary.text(
            text, default=default or "", validate=check, **self._io
        ).unsafe_ask()
        return answer


def arrows_work(*, output_is_terminal: bool, open_console: Callable[[], object]) -> bool:
    """Tell whether this console can draw arrow-key choices."""
    if not output_is_terminal:
        return False
    try:
        open_console()
    except Exception:  # noqa: BLE001 -- e.g. NoConsoleScreenBufferError under mintty: no arrows
        return False
    return True


def prompter() -> Prompter:
    """Return the arrow prompter where this console draws it, else numbers with a notice."""
    write = sys.stdout.write
    if arrows_work(output_is_terminal=sys.stdout.isatty(), open_console=create_output):
        return ArrowPrompter(write)
    line = LinePrompter(input, write)
    line.tell(NO_ARROWS)
    return line
