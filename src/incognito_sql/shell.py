"""Commands printed for the operator to paste, quoted for the shell they type into.

On Windows that is PowerShell; elsewhere a POSIX shell.
"""

import os
import re
import shlex
from collections.abc import Iterable

WINDOWS = os.name == "nt"
_PLAIN = re.compile(r"[\w./:\\=-]+")  # a word PowerShell passes on as typed
_QUOTES = frozenset(map(chr, (0x27, 0x2018, 0x2019, 0x201A, 0x201B)))  # each ends a '...'


def powershell(word: str) -> str:
    """Return ``word`` as PowerShell reads it back: bare, or single-quoted."""
    if word != "--" and _PLAIN.fullmatch(word):  # a bare `--` is PowerShell's own token
        return word
    return "'" + "".join(c * 2 if c in _QUOTES else c for c in word) + "'"


def quote(word: str) -> str:
    """Return ``word`` quoted for the operator's shell."""
    return powershell(word) if WINDOWS else shlex.quote(word)


def join(words: Iterable[str]) -> str:
    """Return a command line of ``words`` for the operator's shell."""
    return " ".join(map(quote, words))
