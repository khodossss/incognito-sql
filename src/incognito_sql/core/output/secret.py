"""Secrets among open cells: keys, tokens, PEM blocks, long high-entropy strings."""

import math
import re
from collections import Counter

_JWT = re.compile(r"eyJ[\w-]*\.[\w-]+\.[\w-]+")
_HEX = re.compile(r"[0-9a-fA-F]{32,}")
_BASE64 = re.compile(r"[A-Za-z0-9+/_-]{40,}={0,2}")
_KEY_PREFIX = re.compile(
    r"(sk-|ghp_|gho_|ghs_|github_pat_|xox[baprs]-|AIza)[\w-]{16,}|AKIA[0-9A-Z]{16}"
)
_MIN_ENTROPY = 4.0


def _entropy(text: str) -> float:
    counts = Counter(text)
    return -sum(n / len(text) * math.log2(n / len(text)) for n in counts.values())


def is_secret(text: str) -> bool:
    """Tell whether text is a key, a token, a PEM block or a long high-entropy string."""
    if "-----BEGIN" in text:
        return True
    if _JWT.fullmatch(text) and len(text) >= 40:  # noqa: PLR2004
        return True
    if _HEX.fullmatch(text) or _KEY_PREFIX.fullmatch(text):
        return True
    if _BASE64.fullmatch(text):
        mixed = any(c.isdigit() for c in text) and any(c.isalpha() for c in text)
        return mixed and _entropy(text) >= _MIN_ENTROPY
    return False
