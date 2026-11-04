"""The L2 oracle on real data: part of a hidden value shown, without the whole of it.

A fragment counts when it is at least ``needed(len(value))`` characters long: the larger
of ``MIN_FRAGMENT`` characters and half the value, and of ``MIN_DIGITS`` for a piece of
digits only. Values shorter than ``MIN_VALUE`` characters are judged by the whole-value
oracle only. Text and values are compared in
the forms of ``incognito_sql.levels.textforms``. Whether a fragment is the tool's own word or
visible anyway (the twin's text, shown columns, the query) is the caller's question:
``Run.windows`` gives the pieces to look for there.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from incognito_sql.levels.textforms import plain, variants

MIN_VALUE = 8
MIN_FRAGMENT = 6
MIN_DIGITS = 8  # a piece of digits only: digits match by chance in any number
_KEYS = (24, 12, 6)  # gram lengths a value is indexed by: the longest that fits its need
_LETTERS = re.compile(r"\w")


def needed(length: int) -> int:
    """Return the shortest fragment of a value of ``length`` characters that counts."""
    return max(MIN_FRAGMENT, -(-length // 2))


@dataclass(frozen=True)
class Run:
    """The longest piece of ``value`` found in a text at one place."""

    value: str
    piece: str

    def windows(self) -> Iterator[str]:
        """Yield every piece of the run as long as the value needs, left to right.

        A piece of digits only needs ``MIN_DIGITS`` at least.
        """
        size = needed(len(self.value))
        digits = max(MIN_DIGITS, size)
        for start in range(len(self.piece) - size + 1):
            window = self.piece[start : start + size]
            if not window.isdigit():
                yield window
            elif (longer := self.piece[start : start + digits]).isdigit() and len(longer) == digits:
                yield longer


class Fragments:
    """Find long enough pieces of hidden values in text; built once per database."""

    def __init__(self, hidden: Iterable[object]) -> None:
        """Index each value by grams sampled so that every long enough piece holds one.

        A piece of ``need`` characters starting anywhere holds a gram of ``key``
        characters starting at a multiple of ``need - key + 1``: one pass of each gram
        length over a text finds every candidate.
        """
        self._index: dict[int, dict[str, list[tuple[str, int]]]] = defaultdict(dict)
        seen: set[str] = set()
        for raw in hidden:
            value = plain(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw))
            if len(value) < MIN_VALUE or value in seen or not _LETTERS.search(value):
                continue
            seen.add(value)
            need = needed(len(value))
            key = next(k for k in _KEYS if k <= need)
            for start in range(0, len(value) - key + 1, need - key + 1):
                self._index[key].setdefault(value[start : start + key], []).append((value, start))
        self.size = len(seen)

    def found(self, text: str) -> list[Run]:
        """Return the runs of hidden values in ``text`` at least as long as they need."""
        runs: dict[tuple[str, str], Run] = {}
        for variant in variants(text):
            for key, grams in self._index.items():
                for at in range(len(variant) - key + 1):
                    for value, start in grams.get(variant[at : at + key], ()):
                        piece = _extend(variant, at, value, start, key)
                        if len(piece) >= needed(len(value)):
                            runs.setdefault((value, piece), Run(value, piece))
        return list(runs.values())


def _extend(text: str, at: int, value: str, start: int, key: int) -> str:
    """Return the longest common piece of ``text`` and ``value`` around a gram match."""
    left = 0
    while left < min(at, start) and text[at - left - 1] == value[start - left - 1]:
        left += 1
    right = key
    while (
        at + right < len(text)
        and start + right < len(value)
        and text[at + right] == value[start + right]
    ):
        right += 1
    return value[start - left : start + right]
