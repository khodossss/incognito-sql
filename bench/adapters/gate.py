"""gate: a stdio MCP proxy; answers of the wrapped server are redacted by key names and regexes.

The release binary 0.11.6 (``gate mcp -- <server>``) in a container of ours, in front of
DBHub (``bench/adapters/dbhub.py``), which has no masking of its own. ``gate mcp`` runs
its Gate 2 only: JSON keys matched by its built-in name classifier or our
``column_denylist``, and value regexes (email, SSN, phone, Luhn cards). Its interception
log and stats log are written to the work directory and scanned. Config:
``config/gate.yaml``.
"""

from pathlib import Path

from bench.adapters import dbhub, launch
from bench.adapters.base import Info
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

VERSION = "0.11.6"
IMAGE = f"bench-gate:{VERSION}"
DIALECTS = dbhub.DIALECTS
INFO = Info(
    name="gate",
    mechanism="MCP proxy; answers redacted by JSON key name and value regexes",
    rung=1,
    version=f"release v{VERSION} (Linux binary); wraps DBHub {dbhub.VERSION} (npm)",
    source="https://github.com/GaaraZhu/gate",
    license="MIT (DBHub: MIT)",
    install="docker build -f bench/adapters/docker/gate.Dockerfile (release binary + DBHub)",
    command=(
        "docker run -i --rm --network container:<dbms> -e GATE_CONFIG -e GATE_LOG_PATH"
        " -e GATE_STATS_PATH -e DSN -v bench/adapters/config:/config:ro -v <work>:/audit"
        f" [-v <world dir>:/data:ro] {IMAGE}"
        " (gate mcp -- dbhub --transport stdio)"
    ),
    tool=dbhub.TOOL,
    arguments=dbhub.ARGUMENT,
)


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start gate and DBHub beside ``db``; SQLite is mounted read-only under ``/data``."""
    image = launch.ensure_image(IMAGE, dockerfile="gate.Dockerfile")
    mounts = {launch.CONFIG: "/config:ro", workdir: "/audit"}
    if db.path is not None:
        mounts[db.path.parent] = f"{dbhub.SQLITE_DIR}:ro"
    log = "/audit/gate-log.jsonl"
    env = {
        "GATE_CONFIG": "/config/gate.yaml",
        "GATE_LOG_PATH": log,
        "GATE_STATS_PATH": log,
        "DSN": dbhub.dsn(db),
    }
    params = launch.container(image, db, env, mounts, [])
    arguments = lambda sql: {dbhub.ARGUMENT: sql}  # noqa: E731
    audit = workdir / "gate-log.jsonl"
    calls = (arguments, dbhub.parse)
    return StdioAdapter(INFO, db.dialect, params, calls, workdir=workdir, audit=audit)
