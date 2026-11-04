"""Strict checks of the values a bind compared with an identifier may carry: numbers.

A check takes one raw form (text) and returns the value to bind, or None when the
text is not a plain spelling of a value the type holds. Every check is narrower
than what any supported DBMS accepts for that type, so a value that passes never
makes the DBMS fail, and one that does not pass is simply not bound.
"""

import re
from dataclasses import dataclass
from decimal import Context, Decimal
from typing import Protocol

_NUMBER = re.compile(r"-?(\d+\.?\d*|\.\d+)([eE][+-]?\d{1,6})?")
_DOLLARS = re.compile(r"(-?)\$(\d{1,3}(?:,\d{3})*|\d+)(\.\d+)?")  # Postgres MONEY: -$1,234.50


class Domain(Protocol):
    """The values one exact type holds."""

    def check(self, raw: str) -> object | None:
        """Return the value to bind for `raw`, or None if the type does not hold it."""


def number(raw: str) -> Decimal | None:
    """Return the value of a plain decimal number; None for any other text."""
    return Decimal(raw) if _NUMBER.fullmatch(raw) else None


@dataclass(frozen=True)
class Integers:
    """Whole numbers in [low, high)."""

    low: int
    high: int

    def check(self, raw: str) -> int | None:
        """Return the integer, if whole and in range."""
        value = number(raw)
        if value is None or value.adjusted() > 80 or value != value.to_integral_value():  # noqa: PLR2004
            return None
        whole = int(value)
        return whole if self.low <= whole < self.high else None


@dataclass(frozen=True)
class Decimals:
    """Exact decimals with at most `precision` digits, `scale` of them after the point."""

    precision: int
    scale: int
    pad: bool = True  # write the value with exactly `scale` decimals

    def check(self, raw: str) -> Decimal | None:
        """Return the decimal, if held exactly."""
        value = number(raw)
        if value is None or not _held(value, self.precision - self.scale, self.scale):
            return None
        if not self.pad:
            return value
        step = Decimal(1).scaleb(-self.scale)
        return value.quantize(step, context=Context(prec=max(self.precision, 1)))


def _held(value: Decimal, whole: int, scale: int) -> bool:
    if not value:
        return True
    _, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)  # noqa: S101 -- finite by the pattern
    zeros = len(digits) - len(bytes(digits).rstrip(b"\0"))
    return value.adjusted() < whole and -(exponent + zeros) <= scale


@dataclass(frozen=True)
class Floats:
    """Binary floating point: zero, or a normal number up to `largest` in magnitude."""

    smallest: Decimal
    largest: Decimal

    def check(self, raw: str) -> float | None:
        """Return the float, if in the normal range."""
        value = number(raw)
        if value is None or (value and not self.smallest <= value.copy_abs() <= self.largest):
            return None
        return float(value)


@dataclass(frozen=True)
class Money:
    """A money amount: its decimal domain within [low, high]; `dollars` also reads -$1,234.50."""

    decimals: Decimals
    low: Decimal
    high: Decimal
    dollars: bool = False

    def check(self, raw: str) -> Decimal | None:
        """Return the amount, if held."""
        spelled = _DOLLARS.fullmatch(raw) if self.dollars else None
        if spelled is not None:
            sign, whole, fraction = spelled.groups()
            raw = sign + whole.replace(",", "") + (fraction or "")
        value = self.decimals.check(raw)
        return value if value is not None and self.low <= value <= self.high else None
