"""The service's bearer token: where it comes from and how long it must be (no SDK import)."""

from collections.abc import Mapping

TOKEN_ENV = "INCOGNITO_SQL_MCP_TOKEN"  # noqa: S105 -- a variable name, not a secret
MIN_TOKEN_CHARS = 32


class TokenError(Exception):
    """The service token is missing or too short; the message never quotes it."""


def service_token(environ: Mapping[str, str]) -> str:
    """Return the bearer token clients must send, from ``INCOGNITO_SQL_MCP_TOKEN``."""
    token = environ.get(TOKEN_ENV, "")
    if len(token) < MIN_TOKEN_CHARS:
        msg = f"environment variable {TOKEN_ENV} must hold at least {MIN_TOKEN_CHARS} characters"
        raise TokenError(msg)
    return token
