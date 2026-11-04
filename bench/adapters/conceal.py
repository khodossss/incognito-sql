"""mcp-server-conceal: a stdio MCP proxy; personal values found by regex become fake ones.

The release binary 0.1.0 in a container of ours, in front of DBHub
(``bench/adapters/dbhub.py``), which has no masking of its own. It scans the text of each
answer of the wrapped server with its patterns (email, phone, SSN, card, IP, URL) and
replaces every match with a consistent fake value; it knows no column. Config
``config/conceal.toml``; its real-to-fake mappings go to a SQLite file in the work
directory, which only the operator reads.
"""

from pathlib import Path

from bench.adapters import dbhub, launch
from bench.adapters.base import Info
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

VERSION = "0.1.0"
IMAGE = f"bench-conceal:{VERSION}"
DIALECTS = dbhub.DIALECTS
INFO = Info(
    name="mcp-server-conceal",
    mechanism="MCP proxy; regex matches in the answer replaced by consistent fake values",
    rung=1,
    version=f"release v{VERSION} (Linux binary); wraps DBHub {dbhub.VERSION} (npm)",
    source="https://github.com/gbrigandi/mcp-server-conceal",
    license="MIT (DBHub: MIT)",
    install="docker build -f bench/adapters/docker/conceal.Dockerfile (release binary + DBHub)",
    command=(
        "docker run -i --rm --network container:<dbms> -e DSN"
        " -v bench/adapters/config:/config:ro -v <work>:/audit"
        f" [-v <world dir>:/data:ro] {IMAGE}"
        " (mcp-server-conceal --target-command dbhub --target-args='--transport stdio')"
    ),
    tool=dbhub.TOOL,
    arguments=dbhub.ARGUMENT,
)


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start the proxy and DBHub beside ``db``; SQLite is mounted read-only under ``/data``."""
    image = launch.ensure_image(IMAGE, dockerfile="conceal.Dockerfile")
    mounts = {launch.CONFIG: "/config:ro", workdir: "/audit"}
    if db.path is not None:
        mounts[db.path.parent] = f"{dbhub.SQLITE_DIR}:ro"
    params = launch.container(image, db, {"DSN": dbhub.dsn(db)}, mounts, [])
    arguments = lambda sql: {dbhub.ARGUMENT: sql}  # noqa: E731
    calls = (arguments, dbhub.parse)
    return StdioAdapter(INFO, db.dialect, params, calls, workdir=workdir)
