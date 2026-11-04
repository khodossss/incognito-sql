"""Token shape and generation."""

import base64
import re
import secrets

TOKEN_RE = re.compile(r"^tk_[a-z2-7]{16}$")


def new_token() -> str:
    """Return a fresh random token: ``tk_`` plus 16 lowercase base32 characters."""
    body = base64.b32encode(secrets.token_bytes(10)).decode("ascii").lower()
    return f"tk_{body}"
