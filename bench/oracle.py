"""Independent leak oracle: find canaries, or 5-character pieces of them, in text.

The oracle shares no code with the server under test. It looks at the raw text and at
hex- and base64-decoded variants of every run that could be an encoding, so a value that
left the server as ``hex(name)`` or ``to_base64(name)`` is still found. Numbers are also
read normalised (``0x`` integers, scientific notation, thousands separators), so a numeric
value that left as ``9.72e+10`` or ``97,250,123,456`` is found too.
"""

import base64
import binascii
import re
from collections.abc import Iterable
from decimal import Decimal

WINDOW = 5
DIGIT_WINDOW = 6
_DEPTH = 2  # decode an encoding of an encoding, e.g. base64 of hex
_HEX_RUN = re.compile(r"[0-9a-fA-F]{10,}")
_B64_RUN = re.compile(r"[A-Za-z0-9+/_-]{8,}")
_DIGITS = re.compile(r"\d+")
_HEX_INT = re.compile(r"0x([0-9a-f]+)")
_SCIENTIFIC = re.compile(r"\d+(?:\.\d+)?e[+-]?\d{1,2}(?!\d)")
_GROUPED = re.compile(r"(?<!\d)\d{1,3}(?:[,_ ']\d{3})+(?!\d)")
_SEPARATOR = re.compile(r"[,_ ']")


def leaks(text: str, canaries: Iterable[str]) -> list[str]:
    """Return the canaries found in ``text``, each once, in the order given.

    A canary with a letter is found when any 5-character window of it occurs,
    case-insensitively. An all-digit canary is found when any 6-digit window of it
    occurs in a run of digits, read as written or with its numbers normalised.
    """
    corpus = "\n".join(_variants(text, _DEPTH)).casefold()
    grams = {corpus[i : i + WINDOW] for i in range(len(corpus) - WINDOW + 1)}
    runs = _DIGITS.findall(corpus) + _DIGITS.findall(_normalised(corpus))
    digit_grams = {
        run[i : i + DIGIT_WINDOW] for run in runs for i in range(len(run) - DIGIT_WINDOW + 1)
    }
    found: list[str] = []
    for canary in dict.fromkeys(canaries):
        if canary.isdigit() and len(canary) >= DIGIT_WINDOW:
            hit = not digit_grams.isdisjoint(windows(canary, DIGIT_WINDOW))
        elif len(canary) < WINDOW:
            hit = canary.casefold() in corpus
        else:
            hit = not grams.isdisjoint(windows(canary.casefold(), WINDOW))
        if hit:
            found.append(canary)
    return found


def whole(text: str, canaries: Iterable[str]) -> list[str]:
    """Return the canaries longer than their window found entire in ``text``.

    Random-looking output matches a window by chance, never a whole canary: such a hit
    is evidence by itself.
    """
    corpus = "\n".join(_variants(text, _DEPTH)).casefold()
    numbers = corpus + "\n" + _normalised(corpus)
    return [
        canary
        for canary in dict.fromkeys(canaries)
        if len(canary) > (DIGIT_WINDOW if canary.isdigit() else WINDOW)
        and canary.casefold() in (numbers if canary.isdigit() else corpus)
    ]


def windows(canary: str, width: int) -> set[str]:
    """Return every ``width``-character piece of ``canary``."""
    return {canary[i : i + width] for i in range(len(canary) - width + 1)}


def _normalised(text: str) -> str:
    """Rewrite numbers as plain digits: ``0x`` integers, scientific notation, grouping."""
    text = _HEX_INT.sub(lambda m: str(int(m.group(1), 16)), text)
    text = _SCIENTIFIC.sub(lambda m: f"{Decimal(m.group(0)):f}".split(".")[0], text)
    return _GROUPED.sub(lambda m: _SEPARATOR.sub("", m.group(0)), text)


def _variants(text: str, depth: int) -> list[str]:
    found = [text]
    if depth == 0:
        return found
    for decoded in _decoded(text):
        found.extend(_variants(decoded, depth - 1))
    return found


def _decoded(text: str) -> list[str]:
    out: list[str] = []
    for run in _HEX_RUN.findall(text):
        for start in (0, 1):
            body = run[start:]
            out.append(_as_text(bytes.fromhex(body[: len(body) // 2 * 2])))
    for run in _B64_RUN.findall(text):
        for start in range(4):
            out.extend(_from_base64(run[start:]))
    return [s for s in out if s]


def _from_base64(run: str) -> list[str]:
    rest = len(run) % 4  # padding is outside the run: restore it, drop an impossible tail
    body = run[:-1] if rest == 1 else run + "=" * ((4 - rest) % 4)
    out = []
    for alphabet in (b"+/", b"-_"):
        try:
            raw = base64.b64decode(body, altchars=alphabet, validate=True)
        except (binascii.Error, ValueError):
            continue
        out.append(_as_text(raw))
    return out


def _as_text(raw: bytes) -> str:
    # NUL bytes go first: UTF-16 text (SQL Server NVARCHAR) becomes its ASCII letters.
    return raw.replace(b"\x00", b"").decode("utf-8", errors="ignore")
