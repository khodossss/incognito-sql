# ruff: noqa: RUF001
"""Second layer: spot values that look like personal data or secrets (linear-time patterns)."""

import math
import re
import unicodedata
from collections.abc import Mapping
from decimal import Decimal

from incognito_sql.core.output.secret import is_secret

_ZERO_WIDTH = re.compile("[\u200b-‍﻿]")
_EMAIL_LOCAL = re.compile(r"[\w.+-]{1,64}\Z")
_EMAIL_DOMAIN = re.compile(r"[\w-]{1,63}(?:\.[\w-]{1,63}){0,8}\.[A-Za-z]{2,24}")
_DATE = re.compile(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}")
_YEAR_RANGE = re.compile(r"\d{4}\s?[-–—]\s?\d{4}")
_PHONE_CHARS = re.compile(r"\+?[\d\s().–—/-]+")
_PLUS_PHONE = re.compile(r"\+\d(?:[\s().–—/-]{0,3}\d){6,}")
_DIGIT_RUN = re.compile(r"\d{10,}")
_CARD = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
_IBAN = re.compile(r"\b[A-Za-z]{2}\d{2}(?: ?[A-Za-z0-9]){11,30}")
_MIN_PHONE_DIGITS = 7
_MAX_CANDIDATES = 50
_MAX_DEPTH = 8
_PHONE_SEPARATORS = " ()-–—/"
_IDENTIFIER_SIZED = 10**9  # an integer part of 10+ digits: a phone, a document number


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2  # noqa: PLR2004
        total += d
    return total % 10 == 0


def _has_email(text: str) -> bool:
    start = 0
    for _ in range(_MAX_CANDIDATES):
        at = text.find("@", start)
        if at < 0:
            return False
        start = at + 1
        local = text[max(0, at - 64) : at]
        if _EMAIL_LOCAL.search(local) and _EMAIL_DOMAIN.match(text[at + 1 : at + 600]):
            return True
    return text.find("@", start) >= 0  # candidates left unexamined: hidden, not passed


def _has_card(text: str) -> bool:
    for n, m in enumerate(_CARD.finditer(text)):
        if n == _MAX_CANDIDATES:
            return True  # candidates left unexamined: hidden, not passed
        if _luhn(_digits(m.group())):  # _CARD matches 13 to 19 digits
            return True
    return False


def _iban_ok(compact: str) -> bool:
    moved = compact[4:] + compact[:4]
    return int("".join(str(int(ch, 36)) for ch in moved)) % 97 == 1


def _has_iban(text: str) -> bool:
    for n, m in enumerate(_IBAN.finditer(text)):
        if n == _MAX_CANDIDATES:
            return True  # candidates left unexamined: hidden, not passed
        compact = m.group().replace(" ", "")  # 15 to 34 characters; int(ch, 36) takes any case
        if any(_iban_ok(compact[:n]) for n in range(len(compact), 14, -1)):
            return True
    return False


def _is_phone(text: str) -> bool:
    if _DIGIT_RUN.fullmatch(text) or _PLUS_PHONE.search(text):
        return True
    body = text.removeprefix("-")
    if not _PHONE_CHARS.fullmatch(body) or len(_digits(body)) < _MIN_PHONE_DIGITS:
        return False
    if _DATE.fullmatch(body) or _YEAR_RANGE.fullmatch(body):
        return False
    return any(ch in body for ch in _PHONE_SEPARATORS) or body.count(".") >= 2  # noqa: PLR2004


def _text_kind(raw: str) -> str | None:
    text = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", raw)).strip()
    if not text:
        return None
    checks = (
        ("email", _has_email),
        ("card", _has_card),
        ("phone", _is_phone),
        ("iban", _has_iban),
        ("secret", is_secret),
    )
    return next((kind for kind, found in checks if found(text)), None)


def _number_personal(value: int | float | Decimal) -> bool:  # noqa: PYI041
    """Tell whether a finite number has an integer part of 10 or more digits."""
    finite = value.is_finite() if isinstance(value, Decimal) else math.isfinite(value)
    return finite and abs(math.trunc(value)) >= _IDENTIFIER_SIZED


def _check(value: object, depth: int) -> str | None:
    if value is None or isinstance(value, bool | bytes | bytearray | memoryview):
        return None
    if isinstance(value, int | float | Decimal):
        return "number" if _number_personal(value) else None
    if isinstance(value, Mapping):
        items = [*value.keys(), *value.values()]
    elif isinstance(value, list | tuple | set | frozenset):
        items = list(value)
    else:
        return _text_kind(str(value))
    if depth >= _MAX_DEPTH:
        return "nested"
    return next((kind for item in items if (kind := _check(item, depth + 1))), None)


def personal_kind(value: object) -> str | None:
    """Name what the value resembles: email, card, phone, iban, secret, number; else None.

    Numbers match when their integer part has 10 or more digits. Containers are
    checked element by element; nesting past the limit is ``nested``. Dates,
    amounts and UUIDs (surrogate ids) are deliberately not matched.
    """
    return _check(value, 0)


def looks_personal(value: object) -> bool:
    """Return True if the value resembles an email, phone, card, IBAN or secret."""
    return personal_kind(value) is not None
