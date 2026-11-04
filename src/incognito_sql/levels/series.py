"""The scripted attacker: one series of yes-or-no questions per target and channel.

Channels: existence (is a value in the column: the target's value and a forged one),
order (is the target below a probe of its form: probes forged until half are below),
length (doubling, then halving, then confirmed with ``=``), prefix (letter by letter,
the whole value when the prefix is all of it) and contains (a substring grown to three
characters). Each question goes out in its forms (``incognito_sql.levels.forms``) until one
is answered; the series stops at the first question with none. Truth comes from the
file itself; judging a claim is ``incognito_sql.levels.infer``'s.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from incognito_sql.levels import forms
from incognito_sql.levels.asker import Asker
from incognito_sql.levels.forms import Shape
from incognito_sql.levels.target import Target, Truth, absent, forge

ALPHABET = " etaoinsrhldcumfpgwybvkxjqz0123456789.@-',/()+#&:;!?*\""  # printable, no LIKE wildcard
_ORDER_PROBES = 4
PIECE = 3  # characters a contains series grows its substring to
_TRIES = 64
_MAX_LENGTH = 1 << 16


@dataclass
class Result:
    """What one series asked and what the attacker claims from it."""

    channel: str
    target: Target
    probes: list[tuple[bool, bool | None]] = field(default_factory=list)  # truth, answer
    claim: str | None = None  # prefix, substring or length the attacker settled on
    whole: bool = False  # the prefix series read the value to its end
    skipped: bool = False  # the tool cannot express the channel's query
    spent: int = 0  # queries, refused forms included
    literals: int = 0  # questions sent, each a value compared with the hidden one
    spend: tuple[int, int] | None = None  # literals and probes the tool's budgets counted


def run_series(asker: Asker, truth: Truth, target: Target, channel: str) -> Result:
    """Run one series against the tool behind ``asker``; ``truth`` judges its answers."""
    asker.series()
    result = Result(channel, target)
    _SERIES[channel](asker, truth, target, result)
    result.skipped, result.spent, result.literals = asker.skipped, asker.spent, len(asker.asked)
    result.spend = asker.spend
    return result


def _ask(asker: Asker, t: Target, shapes: list[Shape]) -> bool | None:
    return asker.ask_any(forms.on_row(t, shapes))


def _existence(asker: Asker, truth: Truth, t: Target, result: Result) -> None:
    fake = absent(truth, t, "existence")
    if fake is None:
        return
    for real, probe in ((True, t.value), (False, fake)):
        answer = asker.ask_any(forms.in_column(t, probe))
        result.probes.append((real, answer))
        if answer is None:
            return


def _order(asker: Asker, truth: Truth, t: Target, result: Result) -> None:
    probes: dict[bool, list[object]] = {True: [], False: []}
    for k in range(_TRIES):
        probe = forge(t.value, f"order.{k}", keep=k % len(t.text))  # 'a…' has none below
        below = truth.below(t, probe)
        if probe != t.value and len(probes[below]) < _ORDER_PROBES // 2:
            probes[below].append(probe)
    if min(map(len, probes.values())) < _ORDER_PROBES // 2:
        return
    for real, probe in sorted(((b, p) for b, ps in probes.items() for p in ps), key=str):
        answer = _ask(asker, t, forms.below(probe))
        result.probes.append((real, answer))
        if answer is None:
            return


def _length(asker: Asker, _: Truth, t: Target, result: Result) -> None:
    def longer(n: int) -> bool | None:
        return _ask(asker, t, forms.length(">", n))

    low, high = 0, 1
    while (answer := longer(high)) and high < _MAX_LENGTH:
        low, high = high, high * 2
    if answer is None:
        return
    while high - low > 1:  # length is in (low, high]
        middle = (low + high) // 2
        answer = longer(middle)
        if answer is None:
            return
        low, high = (middle, high) if answer else (low, middle)
    if _ask(asker, t, forms.length("=", high)):
        result.claim = str(high)


def _grow(asker: Asker, t: Target, shapes: Callable[[str], list[Shape]], known: str) -> str | None:
    """Return the next character after ``known``, '' when none fits, None with no answer."""
    for ch in ALPHABET:
        answer = _ask(asker, t, shapes(known + ch))
        if answer is None:
            return None
        if answer:
            return ch
    return ""


def _prefix(asker: Asker, _: Truth, t: Target, result: Result) -> None:
    known = ""
    while (ch := _grow(asker, t, forms.prefix, known)) is not None:
        if ch:
            known += ch
            result.claim = known
            continue
        result.whole = bool(known) and bool(_ask(asker, t, forms.whole(known)))
        return


def _contains(asker: Asker, _: Truth, t: Target, result: Result) -> None:
    for seed in ALPHABET.strip():
        found = _ask(asker, t, forms.contains(seed))
        if found is None:
            return
        known = seed if found else ""
        while known and len(known) < PIECE:
            ch = _grow(asker, t, forms.contains, known)
            if ch is None:
                return
            known = known + ch if ch else ""
        if known:
            result.claim = known
            return


_SERIES = {
    "existence": _existence,
    "order": _order,
    "length": _length,
    "prefix": _prefix,
    "contains": _contains,
}
