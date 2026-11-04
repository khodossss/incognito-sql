"""Run every probe, print the profile and the holes, return the exit code."""

import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TextIO

import keyring
from sqlalchemy.engine import make_url

from incognito_sql.check.clients import client_findings, client_settings
from incognito_sql.check.probes import (
    Access,
    Finding,
    access,
    environment_findings,
    file_findings,
    keyring_finding,
)
from incognito_sql.connect.clients import valid_variable
from incognito_sql.core.config import load_declaration
from incognito_sql.core.config.report import protection_lines

CLOSED, OPEN, UNKNOWN = 0, 1, 2
_FILE_DIALECTS = ("sqlite", "duckdb")


def _visible_database(dsn: str | None, dialect: str | None) -> Path | None:
    """Return the SQLite or DuckDB file of a DSN this user can see, if any."""
    if dsn is None or dialect not in _FILE_DIALECTS:
        return None
    try:  # a DSN that does not parse names no file; its error may quote a part of it
        database = make_url(dsn).database
    except Exception:  # noqa: BLE001
        return None
    return Path(database) if database and database != ":memory:" else None


def findings(  # noqa: PLR0913
    config: Path | None,
    env_file: Path | None,
    database: Path | None = None,
    *,
    environ: Mapping[str, str],
    home: Path,
    cwd: Path,
    get_password: Callable[[str, str], str | None],
) -> list[Finding]:
    """Collect the probes; what the config names is probed only if this user can read it."""
    dsn_env = dialect = None
    if config is not None and access(config) is Access.READABLE:
        try:
            decl = load_declaration(config)
            dsn_env, dialect = decl.dsn_env, decl.dialect
        except Exception:  # noqa: BLE001, S110 -- a broken config names nothing to probe
            pass
    if dsn_env is not None and not valid_variable(
        dsn_env
    ):  # a DSN or a token, perhaps: never repeat it
        dsn_env = None
    if database is None:
        database = _visible_database(environ.get(dsn_env) if dsn_env else None, dialect)
    found = [
        *file_findings(config, env_file, database),
        *environment_findings(environ, dsn_env),
        keyring_finding(get_password),
        *client_findings(client_settings(home, cwd, environ)),
    ]
    if config is None and env_file is None:
        found.append(
            Finding(
                "the service's files were not named",
                hole=False,
                fix="pass the service's --config and --env-file",
                unknown=True,
            )
        )
    return found


def report(found: list[Finding], out: TextIO | None = None) -> int:
    """Print one line per probe and the verdict: 0 closed, 1 convenient, 2 unknown."""
    out = out or sys.stdout
    for item in found:
        mark = "OPEN  " if item.hole else "??    " if item.unknown else "closed"
        out.write(f"{mark}  {item.what}\n")
    holes = [f for f in found if f.hole]
    unknown = [f for f in found if f.unknown]
    if holes:
        out.write(
            "\nprofile: convenient - an agent running as this user can go around the server\n"
        )
        out.writelines(f"  fix: {item.what}: {item.fix}\n" for item in holes)
        return OPEN
    if unknown:
        out.write("\nprofile: unknown - some probes could not run\n")
        out.writelines(f"  fix: {item.what}: {item.fix}\n" for item in unknown)
        return UNKNOWN
    if not any(f.what.startswith("database file") for f in found):
        out.write(
            "\nnote: no database file was probed; pass --database if it is SQLite or DuckDB\n"
        )
    out.write("\nprofile: closed - this user cannot reach what was probed\n")
    return CLOSED


def protection_report(config: Path | None, out: TextIO | None = None) -> None:
    """Print what the config's protection profiles open, if the config can be read."""
    if config is None or access(config) is not Access.READABLE:
        return
    try:
        lines = protection_lines(load_declaration(config))
    except Exception:  # noqa: BLE001 -- a broken config is reported by the server, not here
        return
    out = out or sys.stdout
    out.write("\n")
    out.writelines(f"{line}\n" for line in lines)


def run_check(config: Path | None, env_file: Path | None, database: Path | None) -> int:
    """Probe as the current user, in the current folder, and print the report."""
    found = findings(
        config,
        env_file,
        database,
        environ=os.environ,
        home=Path.home(),
        cwd=Path.cwd(),
        get_password=keyring.get_password,
    )
    code = report(found)
    protection_report(config)
    return code
