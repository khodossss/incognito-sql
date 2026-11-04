"""The container competitors that read SQLite, started on a set's file from our marking.

Each starts as its adapter in ``bench/adapters/`` starts it for our own world, with two
differences: its configuration is written for the work (``bench.external.masks``) into a
folder mounted as ``/config``, and the file reaches it on a docker volume
(``bench.external.volume``) instead of a host folder.
"""

import dataclasses
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType

from bench.adapters import (
    conceal,
    datacharter,
    dbhub,
    dbmcp,
    dbridge_mcp,
    freepeak_db_mcp,
    gate,
    januscope,
    launch,
    safedb_mcp,
    veil,
)
from bench.adapters.base import Info, Rows
from bench.adapters.calls import Arguments, Parse
from bench.adapters.januscope_answers import parse as januscope_parse
from bench.adapters.mcp_stdio import START_S, StdioAdapter
from bench.dbms import Database
from bench.external import masks
from bench.external.safedb import open_safedb
from bench.external.volume import volume
from bench.external.work import Work

Opener = Callable[[Work, Database, Path], StdioAdapter]
# veil seeds every declared text column before it serves: a forum's free text
# (codebase_community, about 630 000 values) takes it longer than START_S.
VEIL_START_S = 1200.0


@dataclasses.dataclass(frozen=True)
class Launch:
    """One tool's start on a work: its image, files, environment, command and answers."""

    info: Info
    image: str
    files: Mapping[str, str]
    env: Mapping[str, str]
    args: list[str]
    calls: tuple[Arguments, Parse]
    audit: str = ""
    start_s: float = START_S
    work_files: Mapping[str, str] = dataclasses.field(default_factory=dict)  # writable, /audit


def start(how: Launch, work: Work, workdir: Path) -> StdioAdapter:
    """Write the files under ``workdir/config`` and start the tool on the work's volume."""
    folder = workdir / "config"
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in how.files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, encoding="utf-8")
    for name, text in how.work_files.items():
        (workdir / name).write_text(text, encoding="utf-8")
    db = Database("sqlite", f"sqlite:///{work.path.as_posix()}", path=work.path)
    mounts: dict[Path | str, str] = {
        folder: "/config:ro",
        workdir: "/audit",
        volume(work.path): "/data:ro",
    }
    params = launch.container(how.image, db, how.env, mounts, how.args)
    log = workdir / how.audit if how.audit else None
    return StdioAdapter(
        how.info, "sqlite", params, how.calls, workdir=workdir, audit=log, start_s=how.start_s
    )


def _file(work: Work) -> str:
    return f"/data/{work.path.name}"


def _by(key: str) -> Arguments:
    return lambda sql: {key: sql}


def _freepeak(work: Work) -> Launch:
    m = freepeak_db_mcp
    run = ["/app/server", "-t", "stdio", "-c", "/config/freepeak.json"]
    files = {"freepeak.json": masks.freepeak(work)}
    image = launch.ensure_image(m.IMAGE, repo=m.REPO, sha=m.SHA)
    return Launch(m.INFO, image, files, {}, run, (_by("query"), m.parse))


def _gate(work: Work) -> Launch:
    log = "/audit/gate-log.jsonl"
    env = {
        "GATE_CONFIG": "/config/gate.yaml",
        "GATE_LOG_PATH": log,
        "GATE_STATS_PATH": log,
        "DSN": f"sqlite://{_file(work)}",
    }
    image = launch.ensure_image(gate.IMAGE, dockerfile="gate.Dockerfile")
    calls = (_by(dbhub.ARGUMENT), dbhub.parse)
    return Launch(
        gate.INFO, image, {"gate.yaml": masks.gate(work)}, env, [], calls, "gate-log.jsonl"
    )


def _januscope(work: Work) -> Launch:
    env = {"SQLITE_DB_PATH": _file(work), "JANUSCOPE_QUIET": "1"}
    info = dataclasses.replace(januscope.INFO, tool=januscope.TOOLS["sqlite"])
    image = launch.ensure_image(januscope.IMAGE, dockerfile="januscope.Dockerfile")
    files = {"januscope.yaml": masks.januscope(work)}
    args = ["--config", "/config/januscope.yaml"]
    calls = (_by("sql"), januscope_parse)
    return Launch(info, image, files, env, args, calls, "januscope-audit.jsonl")


def _veil(work: Work) -> Launch:
    env = {"VEIL_DB": _file(work), **veil.KEYS}
    image = launch.ensure_image(veil.IMAGE, dockerfile="veil.Dockerfile")
    files = {"veil/schema.prisma": masks.veil(work)}  # the image seeds from /config/veil
    calls = (_by("sql"), veil.parse)
    return Launch(veil.INFO, image, files, env, [], calls, start_s=VEIL_START_S)


def _dbmcp(work: Work) -> Launch:
    env = {"DB_BACKEND": "sqlite", "DB_NAME": _file(work), **dbmcp.PII}
    image = launch.ensure_image(dbmcp.IMAGE, dockerfile="dbmcp.Dockerfile")
    sent = [""]  # the query in flight, to order the keys of its answer

    def arguments(sql: str) -> dict[str, object]:
        sent[0] = sql
        return {"query": sql}

    def read(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001
        return dbmcp.parse(text, is_error, sent[0], "sqlite")

    return Launch(dbmcp.INFO, image, {}, env, ["stdio"], (arguments, read))


def _dbridge(work: Work) -> Launch:
    env = {"DBRIDGE_CONFIG": "/config/dbridge_mcp.json", "DBRIDGE_DB_PATH": _file(work)}
    image = launch.ensure_image(dbridge_mcp.IMAGE, dockerfile="dbridge_mcp.Dockerfile")
    files = {"dbridge_mcp.json": masks.dbridge(work)}
    calls = (_by(dbridge_mcp.ARGUMENT), dbridge_mcp.parse)
    return Launch(dbridge_mcp.INFO, image, files, env, [], calls)


def _conceal(work: Work) -> Launch:
    image = launch.ensure_image(conceal.IMAGE, dockerfile="conceal.Dockerfile")
    files = {"conceal.toml": (launch.CONFIG / "conceal.toml").read_text(encoding="utf-8")}
    calls = (_by(dbhub.ARGUMENT), dbhub.parse)
    env = {"DSN": f"sqlite://{_file(work)}"}
    return Launch(conceal.INFO, image, files, env, [], calls)


def _datacharter(work: Work) -> Launch:
    image = launch.ensure_image(datacharter.IMAGE, dockerfile="datacharter.Dockerfile")
    calls = (datacharter.arguments("sqlite", work.schema), datacharter.parse)
    charter = {"charter.yaml": masks.datacharter(work)}  # the workspace keeps its state there
    return Launch(datacharter.INFO, image, {}, {}, ["/audit"], calls, work_files=charter)


def _opener(plan: Callable[[Work], Launch]) -> Opener:
    return lambda work, _db, workdir: start(plan(work), work, workdir)


# The competitors whose configuration expresses the marking's rules on rows.
ROW_RULES: frozenset[ModuleType] = frozenset()

OPENERS: dict[ModuleType, Opener] = {
    safedb_mcp: open_safedb,
    freepeak_db_mcp: _opener(_freepeak),
    gate: _opener(_gate),
    januscope: _opener(_januscope),
    veil: _opener(_veil),
    dbmcp: _opener(_dbmcp),
    dbridge_mcp: _opener(_dbridge),
    conceal: _opener(_conceal),
    datacharter: _opener(_datacharter),
}
