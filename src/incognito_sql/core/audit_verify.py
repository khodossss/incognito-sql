"""Checking an audit log's chain: the first line edited, missing or inserted, a cut tail.

Lines before the chain began (no ``n``) are counted and passed; from the first chained
line on, every line must carry the next number and the keyed digest of the line before,
and the last must be the head the token store keeps. Nothing of a line is reported but
its place.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from incognito_sql.core.audit_chain import link
from incognito_sql.core.tokens.crypto import Cipher


@dataclass
class Verdict:
    """What the check found."""

    lines: int = 0
    before_chain: int = 0
    checked: int = 0
    anchor: str = "-"
    broken: str | None = None  # the first break, and where

    @property
    def holds(self) -> bool:
        """Tell whether the chain holds from its first link to the anchor."""
        return self.broken is None


def verify(log: Path, cipher: Cipher, head: tuple[int, str] | None) -> Verdict:
    """Check the chain of ``log`` with ``cipher``'s key against the ``head`` kept apart."""
    verdict = Verdict()
    prev, expected, last = "", None, None
    with log.open(encoding="utf-8") as fh:
        for number, raw in enumerate(fh, 1):
            line = raw.rstrip("\r\n")
            verdict.lines += 1
            try:
                entry = json.loads(line)
                n, carried = int(entry["n"]), str(entry["prev"])
            except (ValueError, KeyError, TypeError):
                if expected is None:  # written before the chain began
                    verdict.before_chain += 1
                    prev = line
                    continue
                verdict.broken = f"line {number}: not a link of the chain"
                return verdict
            if expected is not None and n != expected:
                verdict.broken = (
                    f"line {number}: numbers {expected} to {n - 1} are missing"
                    if n > expected
                    else f"line {number}: number {n} inserted or repeated after {expected - 1}"
                )
                return verdict
            if carried != link(cipher, prev):
                verdict.broken = f"line {number - 1} or {number}: edited"
                return verdict
            prev, expected, last = line, n + 1, (n, line)
            verdict.checked += 1
    _anchor(verdict, cipher, head, last)
    return verdict


def _anchor(
    verdict: Verdict, cipher: Cipher, head: tuple[int, str] | None, last: tuple[int, str] | None
) -> None:
    if head is None:
        verdict.anchor = "none kept: a cut tail is not seen"
        return
    kept, digest = head
    if last is None or kept > last[0]:
        end = "no chained line" if last is None else f"number {last[0]}"
        verdict.broken = f"the log ends at {end}, the anchor at {kept}: its tail is cut"
    elif kept < last[0]:
        verdict.broken = f"lines after number {kept} were not written by the service"
    elif digest != link(cipher, last[1]):
        verdict.broken = f"line {verdict.lines}: edited"
    else:
        verdict.anchor = f"number {kept}, matches"
