"""Corpus templates: ``{{TOKEN_*}}`` from one token the server issued, and filler shapes."""

import itertools
import re
from collections.abc import Mapping

_TEMPLATE = re.compile(r"\{\{([A-Z_]+)(?::(.*?))?\}\}")


def token_fills(own: str) -> dict[str, str]:
    """Derive the corpus token templates from one token the server issued."""
    body = own.removeprefix("tk_")
    middle = len(body) // 2
    swapped = "a" if body[middle] != "a" else "b"
    return {
        "TOKEN_OWN": own,
        "TOKEN_OTHER": "tk_" + body[::-1],
        "TOKEN_OTHER_KEY_SAME_ALIAS": "tk_" + body[1:] + body[0],
        "TOKEN_BODY": body,
        "TOKEN_TRUNCATED": own[:-8],
        "TOKEN_FLIPPED": "tk_" + body[:middle] + swapped + body[middle + 1 :],
        "TOKEN_STD_ALPHABET": "tk_" + body.upper(),
    }


def spelling_fills(value: str, count: int = 50) -> dict[str, str]:
    """Return ``SPELLINGS_OWN``: ``count`` quoted case spellings of the token's value."""
    letters = [i for i, ch in enumerate(value) if ch.isalpha()]
    spelled: list[str] = []
    for flags in itertools.islice(itertools.product((False, True), repeat=len(letters)), count):
        chars = list(value.lower())
        for flag, i in zip(flags, letters, strict=True):
            chars[i] = chars[i].upper() if flag else chars[i]
        spelled.append("'" + "".join(chars).replace("'", "''") + "'")
    return {"SPELLINGS_OWN": ", ".join(spelled)}


def expand(sql: str, tokens: Mapping[str, str]) -> str:
    """Fill ``{{NAME}}`` / ``{{NAME:arg}}`` templates; token names come from ``tokens``."""
    return _TEMPLATE.sub(lambda m: _fill(m.group(1), m.group(2), tokens), sql)


def _fill(name: str, arg: str | None, tokens: Mapping[str, str]) -> str:
    if arg is None:
        return tokens[name]
    text, _, count = arg.rpartition(":")
    n = int(count)
    fills = {
        "PAD": lambda: " " * n,
        "PAD_CHAR": lambda: text * n,
        "REPEAT": lambda: text * n,
        "IN_LIST": lambda: ", ".join(str(i) for i in range(n)),
        "NEST": lambda: "(" * n + "1" + ")" * n,
        "JOINS": lambda: "".join(f" JOIN purchases p{i} ON p{i}.id = u.id" for i in range(n)),
    }
    return fills[name]()
