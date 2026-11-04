"""How the wizard asks: a narrow surface, so another way of drawing a choice can replace it.

A secret has no prompt here: `incognito-sql secret` reads it, hidden, in the same terminal.
"""

from collections.abc import Callable, Sequence
from typing import Protocol

_YES = frozenset({"y", "yes"})
_NO = frozenset({"n", "no"})


class Prompter(Protocol):
    """What the wizard needs to ask a human and to tell them something."""

    def tell(self, text: str) -> None:
        """Show a line of text."""

    def one(self, text: str, options: Sequence[str], default: str | None) -> str:
        """Return one of ``options``."""

    def many(self, text: str, options: Sequence[str], chosen: Sequence[str]) -> list[str]:
        """Return a subset of ``options``; ``chosen`` is kept on an empty answer."""

    def yesno(self, text: str, *, default: bool) -> bool:
        """Return the answer to a yes-or-no question."""

    def text(self, text: str, default: str | None, valid: Callable[[str], bool] | None) -> str:
        """Return a line of text that ``valid`` accepts."""


class LinePrompter:
    """A prompter on plain line input: numbered options, a default on an empty line."""

    def __init__(self, read: Callable[[str], str], write: Callable[[str], object]) -> None:
        """Ask with ``read`` (``input`` in a terminal), show with ``write``."""
        self._read = read
        self._write = write

    def tell(self, text: str) -> None:
        """Show a line of text."""
        self._write(text + "\n")

    def one(self, text: str, options: Sequence[str], default: str | None) -> str:
        """Ask for one option by its number or its name."""
        self._list(options)
        while True:
            answer = self._ask(text, default)
            picked = _pick(answer, options)
            if len(picked) == 1:
                return picked[0]
            self.tell("  answer with one number from the list")

    def many(self, text: str, options: Sequence[str], chosen: Sequence[str]) -> list[str]:
        """Ask for numbers and ranges (``1,3-5``); an empty answer keeps ``chosen``."""
        self._list(options)
        while True:
            answer = self._read(f"{text} [{_numbers(options, chosen) or 'none'}]: ").strip()
            if not answer:
                return list(chosen)
            picked = _pick(answer, options)
            if picked:
                return picked
            self.tell("  answer with numbers from the list, e.g. 1,3-5")

    def yesno(self, text: str, *, default: bool) -> bool:
        """Ask y or n; an empty answer is ``default``."""
        while True:
            answer = self._read(f"{text} [{'Y/n' if default else 'y/N'}]: ").strip().casefold()
            if not answer:
                return default
            if answer in _YES or answer in _NO:
                return answer in _YES
            self.tell("  answer y or n")

    def text(self, text: str, default: str | None, valid: Callable[[str], bool] | None) -> str:
        """Ask for a line; ask again until ``valid`` accepts it."""
        while True:
            answer = self._ask(text, default)
            if answer and (valid is None or valid(answer)):
                return answer
            self.tell("  this answer is not accepted here")

    def _ask(self, text: str, default: str | None) -> str:
        shown = f" [{default}]" if default else ""
        return self._read(f"{text}{shown}: ").strip() or (default or "")

    def _list(self, options: Sequence[str]) -> None:
        for number, option in enumerate(options, 1):
            self.tell(f"  {number}. {option}")


def _pick(answer: str, options: Sequence[str]) -> list[str]:
    """Return the options an answer names by number, range or name; [] if any part is wrong."""
    picked: list[str] = []
    for part in filter(None, (p.strip() for p in answer.split(","))):
        if part in options:
            picked.append(part)
            continue
        low, _, high = part.partition("-")
        if not (low.isdigit() and (not high or high.isdigit())):
            return []
        first, last = int(low), int(high or low)
        if not 1 <= first <= last <= len(options):
            return []
        picked.extend(options[first - 1 : last])
    return list(dict.fromkeys(picked))


def _numbers(options: Sequence[str], chosen: Sequence[str]) -> str:
    return ",".join(str(i) for i, option in enumerate(options, 1) if option in chosen)
