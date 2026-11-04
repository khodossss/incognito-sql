"""Name-based hints that a column holds personal data."""

import re

NAME_HINTS: tuple[str, ...] = (
    "name", "phone", "email", "mail", "nick", "passport", "address",
    "password", "ip", "city", "zip", "dob", "birth",
)  # fmt: skip

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
_SECRET = frozenset({"password"})
_QUASI = frozenset({"city", "zip", "dob", "birth"})


def tokens(column: str) -> list[str]:
    """Split a column name on non-alphanumerics and camelCase, lowercased."""
    return [t.lower() for t in _NON_ALNUM.split(_CAMEL.sub("_", column)) if t]


def name_hint(column: str) -> str | None:
    """Return the hint a name token equals, else the longest it starts or ends with, else None."""
    parts = tokens(column)
    for hint in NAME_HINTS:  # an exact token beats a partial match
        if hint in parts:
            return hint
    partial = [h for h in NAME_HINTS if any(t.startswith(h) or t.endswith(h) for t in parts)]
    return max(partial, key=len, default=None)


def suggested_class(hint: str | None) -> str:
    """Return the class to suggest for a candidate; a hint-less candidate is an identifier."""
    if hint in _SECRET:
        return "secret"
    return "quasi" if hint in _QUASI else "identifier"
