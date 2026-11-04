"""The forms in which the real-data oracle compares values and text.

Text and values are compared case-folded with runs of whitespace made one space; a
number is also compared in its plain form (``1234.0`` is ``1234``). JSON string escapes
are read both as written and decoded. Values shorter than ``MIN_LENGTH`` characters are
noise and have no form.
"""

import json
import re
from decimal import Decimal, InvalidOperation

MIN_LENGTH = 4
_DIGITS = 40  # a number further from 1 than 10**40 keeps only its written form
# Numbers a plain form changes: a fraction or an exponent (an integer is already plain).
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+(?:[eE][+-]?\d+)?|[eE][+-]?\d+)(?![\w.])")
_ESCAPE = re.compile(r'\\(?:u[0-9a-fA-F]{4}|["\\/bfnrt])')


def plain(text: str) -> str:
    """Case-fold ``text`` and make every run of whitespace one space."""
    return " ".join(text.casefold().split())


def number(text: str) -> str | None:
    """Return the plain form of a number written as ``text``, or None."""
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or abs(value.adjusted()) > _DIGITS:
        return None  # no plain form worth writing out
    out = f"{value.normalize():f}"
    return "0" if out in {"-0", "0"} else out


def forms(value: object) -> set[str]:
    """Return the forms a value is looked for in; numbers also in their plain form."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = plain(str(value))
    found = {text}
    as_number = number(text) if text else None
    if as_number is not None:
        found.add(as_number)
    return {f for f in found if len(f) >= MIN_LENGTH}


def variants(text: str) -> list[str]:
    """Return the text as written and JSON-decoded, each also with plain numbers."""
    decoded = _ESCAPE.sub(lambda m: json.loads(f'"{m.group(0)}"'), text)
    out = []
    for variant in dict.fromkeys((text, decoded)):
        flat = plain(variant)
        out += [flat, _NUMBER.sub(_plain_number, flat)]
    return list(dict.fromkeys(out))


def _plain_number(match: re.Match[str]) -> str:
    written = match.group(0)
    return number(written) or written
