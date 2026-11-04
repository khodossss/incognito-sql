"""Canary values the oracle can find in windows and nothing else in a channel can produce.

A text canary is ``Zq`` followed by five digit-letter pairs. The digits come from 0, 1,
8, 9 and the letters avoid a-f, so every 5-character window holds a digit that a ``tk_``
token (lowercase base32: a-z, 2-7) never has, a letter that no number has, and is no hex
run. A numeric canary is a digit string whose every 6-digit window holds one of 0, 1, 8,
9 and at least three distinct digits. A date canary is matched by its ``YYYY-MM`` text
and its ``YYYYMMDD`` digits. No two canaries of one world share a window.
"""

import random
from datetime import UTC, datetime
from decimal import Decimal

DIGITS = "0189"
LETTERS = "ghjkmnpqrstuvwxyz"
WINDOW = 5
DIGIT_WINDOW = 6
PAIRS = 5


def _pieces(text: str, width: int) -> set[str]:
    return {text[i : i + width] for i in range(len(text) - width + 1)}


def _signals(window: str) -> bool:
    return any(d in DIGITS for d in window) and len(set(window)) >= 3  # noqa: PLR2004


class CanaryMint:
    """Issue unique canaries from a seeded generator, remembering which must stay hidden."""

    def __init__(self, rng: random.Random) -> None:
        """Mint from ``rng``; the same seed gives the same canaries."""
        self._rng = rng
        self._taken: set[str] = set()
        self.forbidden: list[str] = []
        self.seen: list[str] = []
        self.row_hidden: list[str] = []  # open values a rule on rows hides from the model
        self.reformatted: list[str] = []  # forms a value shows only when reformatted

    def hidden(self) -> str:
        """Return a canary for a value the model must never see."""
        canary = self._fresh()
        self.forbidden.append(canary)
        return canary

    def visible(self) -> str:
        """Return a canary for an open or quasi value the model is meant to see."""
        canary = self._fresh()
        self.seen.append(canary)
        return canary

    def ruled(self) -> str:
        """Return a canary for an open value in a row a rule hides it in."""
        canary = self._fresh()
        self.row_hidden.append(canary)
        return canary

    def digits(self, length: int, lead: str = "") -> str:
        """Return a hidden numeric canary of ``length`` digits starting with ``lead``."""
        while True:
            tail = length - len(lead)
            body = lead + "".join(self._rng.choice("0123456789") for _ in range(tail))
            if body[0] != "0" and self._take_digits(body):
                self.forbidden.append(body)
                return body

    def number(self, length: int = 11) -> int:
        """Return a hidden integer canary, e.g. for a BIGINT identifier."""
        return int(self.digits(length))

    def decimal(self, whole: int, scale: int) -> Decimal:
        """Return a hidden DECIMAL canary with ``whole`` integer and ``scale`` fraction digits."""
        body = self.digits(whole + scale)
        return Decimal(f"{body[:whole]}.{body[whole:]}")

    def moment(self) -> datetime:
        """Return a hidden UTC moment in an unlikely year; date and time parts both fit any zone."""
        while True:
            year, month = self._rng.randint(2100, 2999), self._rng.randint(1, 12)
            day, hour = self._rng.randint(5, 25), self._rng.randint(10, 14)
            when = datetime(year, month, day, hour, self._rng.randint(0, 59), 7, tzinfo=UTC)
            text, digits = when.strftime("%Y-%m"), when.strftime("%Y%m%d")
            if _pieces(text, WINDOW).isdisjoint(self._taken) and self._take_digits(digits):
                self._taken |= _pieces(text, WINDOW)
                self.forbidden += [text, digits]
                self.reformatted.append(digits)
                return when

    def _take_digits(self, body: str) -> bool:
        windows = _pieces(body, DIGIT_WINDOW)
        if not all(map(_signals, windows)) or not self._taken.isdisjoint(windows):
            return False
        self._taken |= windows
        return True

    def _fresh(self) -> str:
        while True:
            body = "".join(
                self._rng.choice(DIGITS) + self._rng.choice(LETTERS) for _ in range(PAIRS)
            )
            canary = "Zq" + body
            windows = _pieces(canary.casefold(), WINDOW)
            if self._taken.isdisjoint(windows):
                self._taken |= windows
                return canary
