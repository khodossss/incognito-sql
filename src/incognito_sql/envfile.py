"""Secrets file: KEY=VALUE lines that fill the environment where it is still unset."""

import re
from collections.abc import MutableMapping
from pathlib import Path

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_QUOTES = ('"', "'")


class EnvFileError(Exception):
    """The secrets file cannot be read; the message never quotes its contents."""


def load_env_file(path: Path, environ: MutableMapping[str, str]) -> None:
    """Set each ``KEY=VALUE`` of the file that ``environ`` does not already hold.

    Blank lines and ``#`` comments are skipped; one pair of matching quotes around
    a value is removed. A bad line is reported by number only: it may hold a secret.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"cannot read the env file ({type(exc).__name__})"  # its path may be a secret
        raise EnvFileError(msg) from None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not _KEY.fullmatch(key):
            msg = f"the env file's line {number} is not KEY=VALUE"
            raise EnvFileError(msg)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in _QUOTES:  # noqa: PLR2004
            value = value[1:-1]
        environ.setdefault(key, value)
