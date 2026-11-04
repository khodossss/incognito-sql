"""The setup the agent runs through the project server: the demo, and a declaration draft.

Each writes into the project's `.incognito-sql` folder only, and answers in words safe
for the model: paths, names of tables and columns, counts; never a DSN or a value.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from incognito_sql.connect.clients import valid_variable
from incognito_sql.core.config import load_declaration
from incognito_sql.core.db import DIALECTS
from incognito_sql.demo import declaration, write_shop
from incognito_sql.init.report import contradictions, reason
from incognito_sql.init.run import StepError, inspect_database
from incognito_sql.init.scaffold import scaffold
from incognito_sql.problems import quiet_problem
from incognito_sql.project import dsn as dsns
from incognito_sql.project.place import FIRST_PORT, PORTS, Place
from incognito_sql.web.run import bind_local

DEMO_DSN = "INCOGNITO_DEMO_DSN"
FILE_DSN = "INCOGNITO_DB_DSN"
_FILE_DIALECTS = {"sqlite": "sqlite:///", "duckdb": "duckdb:///"}


class ActionError(Exception):
    """The action did not run; the message is one safe line."""


@dataclass(frozen=True)
class Draft:
    """What `draft_declaration` did: the file, and its text or the contradictions found."""

    path: Path
    written: bool
    text: str
    found: list[str]


def free_port(place: Place, taken: Callable[[int], bool] | None = None) -> int:
    """Return the first free cards port from this project's own starting point."""
    busy = taken or _busy
    start = place.first_port() - FIRST_PORT
    for step in range(PORTS):
        port = FIRST_PORT + (start + step) % PORTS
        if not busy(port):
            return port
    msg = "no free port for the cards"
    raise ActionError(msg)


def _busy(port: int) -> bool:
    sock = bind_local(port)
    if sock is None:
        return True
    sock.close()
    return False


def create_demo(place: Place, port: int) -> Path:
    """Write the invented shop and its declaration into the project; return the declaration."""
    if place.config.exists():
        msg = "the project has a declaration already: the demo would replace it"
        raise ActionError(msg)
    try:
        place.prepare()
        place.demo.parent.mkdir(parents=True, exist_ok=True)
        if place.demo.exists():
            place.demo.unlink()
        write_shop(place.demo)
        dsns.keep(place.env_file, DEMO_DSN, f"sqlite:///{place.demo.resolve().as_posix()}")
        text = declaration(DEMO_DSN) + f"web_port: {port}\n"
        place.config.write_text(text, encoding="utf-8")
    except OSError as exc:  # its text repeats the path
        msg = f"cannot write the demo: {type(exc).__name__}"
        raise ActionError(msg) from None
    return place.config


def draft_declaration(  # noqa: PLR0913 -- the tool's own arguments
    place: Place,
    port: int,
    dialect: str,
    *,
    dsn_env: str | None,
    database_file: Path | None,
    find: Callable[[str, Path], dsns.Found | None],
    sample: bool = True,
) -> Draft:
    """Write a declaration draft from the database's schema, or list its contradictions."""
    if dialect not in DIALECTS:
        msg = f"dialect is one of {', '.join(DIALECTS)}"
        raise ActionError(msg)
    name, dsn = _dsn(place, dialect, dsn_env, database_file, find)
    try:
        catalog, samples, missed = inspect_database(dsn, dialect, use_sample=sample)
    except StepError as exc:
        raise ActionError(str(exc)) from None
    if place.config.exists():
        try:
            decl = load_declaration(place.config)
        except Exception as exc:  # noqa: BLE001 -- file, YAML or schema: any is a bad config
            msg = f"the declaration cannot be read: {quiet_problem(exc)}"
            raise ActionError(msg) from None
        return Draft(place.config, False, "", contradictions(decl, samples))  # noqa: FBT003
    text = scaffold(catalog, samples, missed=missed, dsn_env=name, dialect=dialect)
    text += f"web_port: {port}\n"
    try:
        place.prepare()
        place.config.write_text(text, encoding="utf-8")
    except OSError as exc:
        msg = f"cannot write the declaration: {type(exc).__name__}"
        raise ActionError(msg) from None
    found = [
        f"{t}.{c}: {why}"
        for t, cols in catalog.columns.items()
        for c in cols
        if (why := reason(t, c, samples)) is not None
    ]
    return Draft(place.config, True, text, found)  # noqa: FBT003


def _dsn(
    place: Place,
    dialect: str,
    dsn_env: str | None,
    database_file: Path | None,
    find: Callable[[str, Path], dsns.Found | None],
) -> tuple[str, str]:
    """Return the DSN's variable name and the DSN: a database file's is kept in the project."""
    if dsn_env is not None and not valid_variable(dsn_env):  # a DSN, perhaps: never repeated
        msg = "dsn_env takes a variable's NAME in upper case (e.g. SHOP_DSN)"
        raise ActionError(msg)
    if database_file is not None:
        prefix = _FILE_DIALECTS.get(dialect)
        if prefix is None:
            msg = "database_file is for sqlite or duckdb; other databases take dsn_env"
            raise ActionError(msg)
        if not database_file.is_file():
            msg = "database_file is no file"
            raise ActionError(msg)
        dsn = prefix + database_file.resolve().as_posix()
        name = dsn_env or FILE_DSN
        place.prepare()
        dsns.keep(place.env_file, name, dsn)
        return name, dsn
    if not dsn_env:
        msg = "give dsn_env, the variable the human set with `secret`, or database_file"
        raise ActionError(msg)
    found = find(dsn_env, place.env_file)
    if found is None:
        msg = f"the variable {dsn_env} is not set: the human sets it with `secret` first"
        raise ActionError(msg)
    return dsn_env, found.dsn
