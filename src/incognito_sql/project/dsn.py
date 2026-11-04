"""Finding a declaration's DSN by its variable's name, read afresh on every look.

The project's own `.env` comes first: a demo or a database file written there is this
project's, even when the user's environment holds an older value under the same name.
Then the server's environment, then (Windows) the user's variable as stored now, so a
variable `secret` set after the client started is seen without a restart.
"""

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from incognito_sql.envfile import EnvFileError, load_env_file

PROJECT, ENVIRONMENT, USER = "the project's .env", "the environment", "your user's variables"


@dataclass(frozen=True)
class Found:
    """A DSN and where it was found (that name is safe to show; the DSN is not)."""

    dsn: str
    source: str


def find(
    name: str,
    env_file: Path,
    environ: Mapping[str, str],
    user: Callable[[str], str | None],
) -> Found | None:
    """Return the DSN named ``name``, or None when no place holds it."""
    if env_file.exists():
        values: dict[str, str] = {}
        try:
            load_env_file(env_file, values)
        except EnvFileError:
            values = {}
        if values.get(name):
            return Found(values[name], PROJECT)
    if environ.get(name):
        return Found(environ[name], ENVIRONMENT)
    stored = user(name)
    return Found(stored, USER) if stored else None


def user_value(name: str) -> str | None:
    """Return the user's variable ``name`` as stored now (Windows), else None."""
    if sys.platform != "win32":
        return None
    import winreg  # noqa: PLC0415 -- Windows only

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return value if isinstance(value, str) and value else None


def keep(env_file: Path, name: str, value: str) -> None:
    """Add or replace ``name=value`` in the project's `.env` (only DSNs that are no secret)."""
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    kept = [line for line in lines if not line.startswith(f"{name}=")]
    kept.append(f"{name}={value}")
    env_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
