"""A target of the inference series, the truth about it, and probes of its form.

A target is one hidden value of one row, the row addressed by a shown column whose
values are unique in its table, so a series asks about that row alone. The truth comes
from the database itself, read by the caller (``Truth``), never from the protection.
Probes that must not be in the column are forged from a value: every letter and digit
replaced by another of its kind, the rest kept.
"""

import hashlib
from dataclasses import dataclass
from typing import Protocol

MIN_TARGET = 4  # characters: a shorter value has no prefix or substring of 3 worth a fact
_TRIES = 64


@dataclass(frozen=True)
class Target:
    """The value of ``column`` in the row of ``table`` where ``key`` is ``row``."""

    table: str
    key: str
    row: object
    column: str
    value: object

    @property
    def text(self) -> str:
        """Return the value as text."""
        return str(self.value)


class Truth(Protocol):
    """The database read directly: what the series' answers are judged against."""

    def below(self, target: Target, probe: object) -> bool:
        """Tell whether the target's value sorts below ``probe`` in the database."""
        ...

    def holds(self, target: Target, value: object) -> bool:
        """Tell whether any row of the target's column holds ``value``."""
        ...


def forge(value: object, salt: str, keep: int = 0) -> object:
    """Return a value of the same form as ``value``: same type, letters and digits changed.

    The first ``keep`` characters stay as they are.
    """
    text = str(value)
    digest = hashlib.sha256(f"{salt}|{text}".encode()).digest()
    chars = []
    for i, ch in enumerate(text):
        byte = digest[i % len(digest)]
        if i < keep:
            pass
        elif ch.isdigit():  # another digit, either side of it; a number keeps its first digit
            ch = str((int(ch) + 1 + byte % 9) % 10 or 1 + byte % 9)  # noqa: PLW2901
        elif isinstance(value, str) and ch.isascii() and ch.isalpha():
            base = ord("a") if ch.islower() else ord("A")
            ch = chr(base + (ord(ch) - base + 1 + byte % 25) % 26)  # noqa: PLW2901
        chars.append(ch)
    forged = "".join(chars)
    if isinstance(value, int):
        return int(forged)
    if isinstance(value, float):
        return float(forged)
    return forged


def absent(truth: Truth, target: Target, salt: str) -> object | None:
    """Return a forged value the target's column does not hold, or None."""
    for k in range(_TRIES):
        probe = forge(target.value, f"{salt}.{k}")
        if probe != target.value and not truth.holds(target, probe):
            return probe
    return None
