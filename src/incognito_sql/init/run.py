"""The `init` command: write a scaffold, or list contradictions of an existing file."""

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from incognito_sql.connect.clients import valid_variable
from incognito_sql.core.config import load_declaration
from incognito_sql.core.db import DIALECTS, make_engine
from incognito_sql.core.sql.catalog import Catalog, reflect
from incognito_sql.envfile import EnvFileError, load_env_file
from incognito_sql.init.report import Samples, contradictions, reason
from incognito_sql.init.sampling import sample
from incognito_sql.init.scaffold import scaffold
from incognito_sql.problems import quiet_problem

if TYPE_CHECKING:
    import argparse

EXIT_FAILED = 1
EXIT_USAGE = 2
_FILE_MODE = 0o600


class StepError(Exception):
    """One safe line naming the failed step, and the exit code it ends with."""

    def __init__(self, message: str, code: int = EXIT_FAILED) -> None:
        """Hold the line and the exit code."""
        super().__init__(message)
        self.code = code


def _dsn(dsn_env: str, env_file: Path | None) -> str:
    """Return the DSN the variable holds, the --env-file read first."""
    if not valid_variable(dsn_env):  # a DSN or a token, perhaps: never repeat it
        msg = "--dsn-env takes a variable's NAME in upper case (e.g. SHOP_DSN)"
        raise StepError(msg, EXIT_USAGE)
    if env_file is not None:
        try:
            load_env_file(env_file, os.environ)
        except EnvFileError:  # its message names the file as typed
            msg = "cannot read the --env-file"
            raise StepError(msg) from None
    dsn = os.environ.get(dsn_env)
    if not dsn:
        msg = "the variable named by --dsn-env is not set"
        raise StepError(msg, EXIT_USAGE)
    return dsn


def add_init_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the `init` subcommand."""
    init = commands.add_parser("init", help="write a declaration scaffold, or list contradictions")
    init.add_argument("--dsn-env", required=True, help="environment variable with the DSN")
    init.add_argument("--dialect", required=True, choices=DIALECTS)
    init.add_argument("--no-sample", action="store_true", help="do not read values")
    init.add_argument("--out", type=Path, required=True, help="scaffold file to write")
    init.add_argument("--env-file", type=Path, help="KEY=VALUE secrets for unset variables")


def _fail(message: str, code: int) -> int:
    sys.stderr.write(f"incognito-sql: {message}\n")
    return code


def _write_new(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


_RESOLVE = (
    "declare each such column hidden (remove it), or, if its values are not personal, "
    "list it under verified_open\n"
)


def _existing(out: Path, samples: Samples | None, missed: int) -> int:
    try:
        decl = load_declaration(out)
    except Exception as exc:  # noqa: BLE001 -- file, YAML or schema: any is a bad config
        return _fail(f"cannot read the --out file: {quiet_problem(exc)}", EXIT_FAILED)
    found = contradictions(decl, samples)
    sys.stdout.write(f"the --out file exists and is left as is; contradictions: {len(found)}\n")
    sys.stdout.writelines(f"{line}\n" for line in found)
    if found:
        sys.stdout.write(_RESOLVE)
    _report_missed(missed)
    return 0


def _report_missed(missed: int) -> None:
    if missed:
        sys.stdout.write(f"{missed} column{'' if missed == 1 else 's'} not sampled\n")


def inspect_database(
    dsn: str, dialect: str, *, use_sample: bool
) -> tuple[Catalog, Samples | None, frozenset[tuple[str, str]]]:
    """Open the database, read the schema and optionally sample; failures name the step."""
    step = "open the database"
    try:
        engine = make_engine(dsn, dialect)
        try:
            step = "read the schema"
            catalog = reflect(engine, dialect)
            step = "sample the values"
            samples, missed = (
                sample(engine, catalog, dialect) if use_sample else (None, frozenset())
            )
        finally:
            engine.dispose()
    except Exception as exc:  # noqa: BLE001 -- driver text may quote the DSN
        msg = f"cannot {step} ({type(exc).__name__})"
        raise StepError(msg) from None
    return catalog, samples, missed


def run_init(
    dsn_env: str, dialect: str, out: Path, *, use_sample: bool, env_file: Path | None = None
) -> int:
    """Run `init`; return the process exit code. Output never carries a sampled value."""
    try:
        dsn = _dsn(dsn_env, env_file)
        catalog, samples, missed = inspect_database(dsn, dialect, use_sample=use_sample)
    except StepError as exc:
        return _fail(str(exc), exc.code)
    if out.exists():
        return _existing(out, samples, len(missed))
    text = scaffold(catalog, samples, missed=missed, dsn_env=dsn_env, dialect=dialect)
    try:
        _write_new(out, text)
    except OSError as exc:
        return _fail(f"cannot write the --out file: {type(exc).__name__}", EXIT_FAILED)
    count = sum(
        reason(t, c, samples) is not None for t, cols in catalog.columns.items() for c in cols
    )
    tables = len(catalog.columns)
    sys.stdout.write(f"scaffold written to {out}: {tables} tables, {count} candidates\n")
    _report_missed(len(missed))
    return 0
