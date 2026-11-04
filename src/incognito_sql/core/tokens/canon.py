"""Canonical form of a value, used to give equal values the same token."""


def canonical(value: object) -> str:
    """Return the canonical text of a value: trimmed, single-spaced, case-folded."""
    return " ".join(str(value).split()).casefold()
