"""The full run: the world on each DBMS, every tool that supports it, one report.

A tool that cannot start, lacks the DBMS or finds it down gets a ``not_run`` row and the reason.
"""

import contextlib
import datetime as dt
import platform
import sqlite3
import tempfile
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

import duckdb

from bench import dbms
from bench.adapters.base import Adapter, Info, NotRunError
from bench.adapters.incognito import open_incognito, profile_infos
from bench.adapters.raw import INFO as RAW
from bench.adapters.raw import RawAdapter
from bench.adapters.roster import COMPETITORS
from bench.cases import Case
from bench.profiles import PROFILES
from bench.report import Report
from bench.run import run
from bench.schema import DIALECTS
from bench.tasks import Task
from bench.world import World

IMAGES = {
    "postgres": "postgres:16-alpine",
    "mysql": "mysql:8.4",
    "tsql": "mcr.microsoft.com/mssql/server:2022-latest",
    "sqlite": f"SQLite {sqlite3.sqlite_version} (Python sqlite3)",
    "duckdb": f"DuckDB {duckdb.__version__}",
}


def run_all(  # noqa: PLR0913, PLR0917 -- the whole run, as the CLI asks for it
    world: World,
    corpus: Sequence[Case],
    tasks: Sequence[Task],
    dialects: Sequence[str],
    only: Sequence[str] | None,
    workdir: Path | None,
) -> tuple[Report, dict[str, str]]:
    """Run every wanted tool on every wanted DBMS; return the report and run facts.

    Tools write their files under ``workdir``; without one, a temporary directory that
    is removed when the run ends.
    """
    report = Report()
    with contextlib.ExitStack() as stack:
        if workdir is None:
            temporary = tempfile.TemporaryDirectory(
                prefix="incognito-bench-", ignore_cleanup_errors=True
            )
            workdir = Path(stack.enter_context(temporary))
        for dialect in (d for d in DIALECTS if d in dialects):
            _run_on(world, (corpus, tasks), dialect, workdir / dialect, report, only)
    return report, _facts(dialects)


def _run_on(  # noqa: PLR0913, PLR0917 -- one DBMS of the run
    world: World,
    work: tuple[Sequence[Case], Sequence[Task]],
    dialect: str,
    place: Path,
    report: Report,
    only: Sequence[str] | None,
) -> None:
    place.mkdir(parents=True, exist_ok=True)
    started = False
    try:
        with dbms.opened(dialect, world.statements(dialect), limit=dbms.LIMIT_S) as db:
            started = True
            adapters = _open(world, db, place, report, only)
            try:
                report.add(run(adapters, *work, world).rows)
            finally:
                for adapter in adapters:
                    adapter.close()
    except Exception as exc:
        if started:
            raise
        for info in _infos(only):  # a DBMS that cannot start: a row for every tool
            report.not_run(info, dialect, f"{dialect} did not start: {type(exc).__name__}")


def _open(
    world: World, db: dbms.Database, place: Path, report: Report, only: Sequence[str] | None
) -> list[Adapter]:
    adapters: list[Adapter] = []
    if _wanted(RAW.name, only):
        adapters.append(RawAdapter(db))
    for tool in COMPETITORS:
        info = tool.INFO
        if not _wanted(info.name, only):
            continue
        if db.dialect not in tool.DIALECTS:
            report.not_run(info, db.dialect, f"supports {', '.join(tool.DIALECTS)} only")
            continue
        workdir = place / info.name
        workdir.mkdir(exist_ok=True)
        try:
            adapters.append(tool.open_adapter(db, workdir))
        except NotRunError as exc:
            report.not_run(info, db.dialect, str(exc))
    if any(_wanted(i.name, only) for i in profile_infos(PROFILES)):
        opened = open_incognito(world, db, place, PROFILES)
        adapters += [a for a in opened if _wanted(a.info.name, only)]
        for extra in (a for a in opened if not _wanted(a.info.name, only)):
            extra.close()
    return adapters


def _wanted(name: str, only: Sequence[str] | None) -> bool:
    return only is None or name in only


def _infos(only: Sequence[str] | None) -> list[Info]:
    infos = [RAW, *(t.INFO for t in COMPETITORS), *profile_infos(PROFILES)]
    return [i for i in infos if _wanted(i.name, only)]


def _facts(dialects: Sequence[str]) -> dict[str, str]:
    return {
        "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "platform": f"{platform.system()} {platform.release()}, Python {platform.python_version()}",
        "sqlglot": version("sqlglot"),
        "dbms": "; ".join(IMAGES[d] for d in DIALECTS if d in dialects),
    }
