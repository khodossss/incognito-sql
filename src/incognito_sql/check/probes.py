"""Read-only probes of what this user can reach: the service's files, key and database login."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from incognito_sql.core.tokens.crypto import ENV_KEY, KEYRING_USER

# A database login with a password: scheme of a DBMS driver, then user:password@.
_DSN_WITH_PASSWORD = re.compile(
    r"^(postgres(ql)?|mysql|mariadb|mssql|oracle|redshift|cockroachdb|snowflake|clickhouse)"
    r"(\+[a-z0-9_]+)?://[^/:@\s]+:[^@\s]+@",
    re.IGNORECASE,
)
_LOCK = "readable only by the service's OS user and administrators"
_ENV_FIX = "set it only in the service's environment or secrets file"


class Access(Enum):
    """What opening a file for reading did."""

    READABLE = "readable"
    DENIED = "denied"
    MISSING = "missing"


@dataclass(frozen=True)
class Finding:
    """One probe's outcome.

    ``hole``: an agent could go around the server here. ``unknown``: the probe
    could not run (a path that does not exist), so it proves nothing.
    """

    what: str
    hole: bool
    fix: str = ""
    unknown: bool = False


def access(path: Path) -> Access:
    """Try to open the file for reading (nothing is read)."""
    try:
        with path.open("rb"):
            return Access.READABLE
    except PermissionError:  # denied, or a folder on the way this user cannot enter
        return Access.DENIED
    except OSError:  # not found, or a path this OS cannot name: the probe proves nothing
        return Access.MISSING


def file_finding(what: str, path: Path, fix: str) -> Finding:
    """Probe one file: readable is a hole, missing is unknown, denied is closed.

    The finding names the file by its argument, never by the path typed: a pasted
    secret is not repeated.
    """
    seen = access(path)
    if seen is Access.MISSING:
        return Finding(f"{what} not found", hole=False, fix="check the path", unknown=True)
    return Finding(what, hole=seen is Access.READABLE, fix=fix)


def file_findings(
    config: Path | None, env_file: Path | None, database: Path | None
) -> list[Finding]:
    """Probe the secrets file, the token store next to the config, and a database file."""
    found: list[Finding] = []
    if env_file is not None:
        found.append(file_finding("secrets file (--env-file)", env_file, f"make it {_LOCK}"))
    if config is not None:
        tokens = config.parent / f"{config.stem}.tokens.db"
        found.append(file_finding("token store next to --config", tokens, f"make it {_LOCK}"))
    if database is not None:
        fix = "make it readable only by the service's OS user"
        found.append(file_finding("database file (--database)", database, fix))
    return found


def environment_findings(environ: Mapping[str, str], dsn_env: str | None) -> list[Finding]:
    """Probe this process's environment for the key and for a database login."""
    found = [Finding(f"{ENV_KEY} in this environment", ENV_KEY in environ, _ENV_FIX)]
    if dsn_env is not None:
        found.append(Finding(f"{dsn_env} in this environment", dsn_env in environ, _ENV_FIX))
    logins = sorted(name for name, value in environ.items() if _DSN_WITH_PASSWORD.match(value))
    found.extend(
        Finding(f"database login with a password in {name}", hole=True, fix=_ENV_FIX)
        for name in logins
        if name != dsn_env
    )
    return found


def keyring_finding(get_password: Callable[[str, str], str | None]) -> Finding:
    """Probe this user's OS keyring for the value key."""
    try:
        held = get_password("incognito-sql", KEYRING_USER) is not None
    except Exception:  # noqa: BLE001 -- no usable keyring means nothing to read
        held = False
    return Finding(
        "value key in this user's OS keyring",
        hole=held,
        fix="keep the key in the service user's keyring or secrets file only",
    )
