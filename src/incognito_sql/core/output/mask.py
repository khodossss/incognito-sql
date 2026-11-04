"""Open cells as the model sees them: plain JSON, or masked where they look personal."""

import math
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal

from incognito_sql.core.output.detect import personal_kind

MASK = "\u2039hidden: looks like personal data\u203a"
_BYTES = "\u2039bytes\u203a"


def rounded(value: object) -> object:
    """Keep 12 significant digits of a float: the rest carries the summation order."""
    if isinstance(value, float) and math.isfinite(value):
        return float(f"{value:.12g}")
    return value


_EXACT_INT = 2**53  # integers a float holds exactly
_WHOLE_DECIMAL = 10**30  # printed as digits; beyond, as 1E+N


def spelled_once(value: object) -> object:
    """Print a number one way whatever its type: `1.0` and `1` alike, `1.50` as `1.5`."""
    if isinstance(value, float) and value.is_integer() and abs(value) < _EXACT_INT:
        return int(value)
    if isinstance(value, Decimal) and value.is_finite():
        whole = value == value.to_integral_value() and abs(value) < _WHOLE_DECIMAL
        return int(value) if whole else value.normalize()
    return value


def plain(value: object) -> object:
    """JSON-safe form of an open cell: Decimal as text, dates as ISO, bytes as a placeholder."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return _BYTES
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


class Masker:
    """Masks the open cells of one answer that look like personal data.

    ``link`` turns a masked value into a link only a signed-in human can open;
    without it the mask is plain text. Output columns in ``checked`` were marked
    open and checked by a human and pass unexamined. ``found`` maps each masked
    output column to the first kind of personal data seen in it, never the value.
    """

    def __init__(
        self,
        link: Callable[[object], str] | None = None,
        checked: frozenset[int] = frozenset(),
    ) -> None:
        """Mask with ``link`` (or plain text), skipping the ``checked`` columns."""
        self._link = link
        self._checked = checked
        self.found: dict[int, str] = {}

    def cell(self, index: int, value: object) -> object:
        """Return the cell of output column ``index`` as the model may see it."""
        value = rounded(value)
        if index in self._checked or isinstance(
            value, datetime | date | bytes | bytearray | memoryview
        ):
            return plain(value)
        kind = personal_kind(value)
        if kind is None:
            return plain(value)
        self.found.setdefault(index, kind)
        return self._link(value) if self._link else MASK
