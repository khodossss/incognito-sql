"""`incognito-sql try`: print the verdict on one query; exit 0 answered, 1 refused, 2 not tried."""

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from incognito_sql.core.config import Declaration, load_declaration
from incognito_sql.core.db import make_engine
from incognito_sql.core.sql.catalog import Catalog, reflect
from incognito_sql.envfile import EnvFileError, load_env_file
from incognito_sql.mcp.refusals import GUIDE
from incognito_sql.problems import quiet_problem
from incognito_sql.trial.verdict import Verdict, verdict

if TYPE_CHECKING:
    import argparse

ANSWERED, REFUSED, NOT_TRIED = 0, 1, 2
UNCHECKED = "not checked here: tokens in the query, the literal budget, the database itself"


def add_try_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the `try` subcommand."""
    tried = commands.add_parser(
        "try", help="show what the server would do with one query, without running it"
    )
    tried.add_argument("--config", type=Path, required=True, help="field declaration (YAML)")
    tried.add_argument("--env-file", type=Path, help="KEY=VALUE secrets for unset variables")
    tried.add_argument("sql", help="the query, as the model would send it")


class _NotTried(Exception):  # noqa: N818 -- an outcome, not an error of try itself
    """The probe could not start; the message repeats nothing typed."""


def run_try(config: Path, env_file: Path | None, sql: str) -> int:
    """Read the schema, judge ``sql`` as the server would, and print the verdict."""
    try:
        decl, catalog = _opened(config, env_file)
    except _NotTried as exc:
        return _fail(str(exc))
    try:
        found = verdict(sql, decl, catalog)
    except Exception as exc:  # noqa: BLE001 -- a bug must not print the query's text
        return _fail(f"the probe failed ({type(exc).__name__})")
    report(found)
    return ANSWERED if found.error is None else REFUSED


def _opened(config: Path, env_file: Path | None) -> tuple[Declaration, Catalog]:
    """Load the secrets file and the config, and read the database's schema."""
    try:
        if env_file is not None:
            load_env_file(env_file, os.environ)
    except EnvFileError:  # its message names the file as typed: a secret, perhaps
        msg = "cannot read the --env-file"
        raise _NotTried(msg) from None
    try:
        decl = load_declaration(config)
    except Exception as exc:  # noqa: BLE001 -- file, YAML or schema: any is a bad config
        msg = f"cannot read the config: {quiet_problem(exc)}"
        raise _NotTried(msg) from None
    dsn = os.environ.get(decl.dsn_env)
    if not dsn:
        msg = "the variable named by the config's dsn_env is not set"
        raise _NotTried(msg)
    try:
        return decl, _schema(dsn, decl.dialect)
    except Exception as exc:  # noqa: BLE001 -- driver text may quote the DSN
        msg = f"cannot read the schema ({type(exc).__name__})"
        raise _NotTried(msg) from None


def report(found: Verdict, out: TextIO | None = None) -> None:
    """Print the verdict, the hint of a refusal, the columns read and the output's shape.

    Nothing of the query's own text is repeated: its literals may be values.
    """
    out = out or sys.stdout
    if found.error is None and found.tokens:
        out.write("verdict: answered if every token in it is live (try reads no token store)\n")
    elif found.error is None:
        out.write("verdict: answered\n")
    else:
        retry, hint = GUIDE.get(found.error, (None, None))
        out.write(
            f"verdict: refused: {found.error}" + (f" (retry: {retry})" if retry else "") + "\n"
        )
        if hint:
            out.write(f"hint: {hint}\n")
    if found.reads:
        out.write("reads:\n")
        out.writelines(f"  {t}.{c}: {cls}\n" for t, c, cls in found.reads)
    if found.outputs:
        shape = ", ".join(f"{i}: {kind}" for i, kind in enumerate(found.outputs, 1))
        out.write(f"output columns: {shape}\n")
    out.write(f"{UNCHECKED}\n")


def _schema(dsn: str, dialect: str) -> Catalog:
    engine = make_engine(dsn, dialect)
    try:
        return reflect(engine, dialect)
    finally:
        engine.dispose()


def _fail(message: str) -> int:
    sys.stderr.write(f"incognito-sql: {message}\n")
    return NOT_TRIED
