"""dbridge-mcp: columns hidden from the model or masked in its answers, by column name.

Published npm package ``dbridge-mcp`` 0.7.1, its registry tarball checked against its
digest, run in a container of ours. Config ``config/dbridge_mcp.json``, as its README's
"Column masking" advises: true secrets in ``hiddenColumns`` (a query naming one is
refused), the other personal columns in ``maskedColumns`` with the ``full`` strategy
(still usable in ``WHERE`` and ``GROUP BY``, ``***`` in the answer), and the tables the
world does not declare in ``blockedTables``. Both lists match a column name, whatever its
table and case. The connection string goes in ``DBRIDGE_DB_PATH``, as its README says for
production.
"""

import json
from pathlib import Path

from bench.adapters import launch
from bench.adapters.base import ANSWERED, REFUSED, Info, Rows, dict_rows
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

VERSION = "0.7.1"
IMAGE = f"bench-dbridge-mcp:{VERSION}"
DIALECTS = ("postgres", "mysql", "sqlite")
TOOL, ARGUMENT = "run_query", "sql"
INFO = Info(
    name="dbridge-mcp",
    mechanism="columns hidden (query refused) or masked in the answer, by column name",
    rung=1,
    version=f"{VERSION} (npm)",
    source="https://github.com/ugurcl/dbridge-mcp",
    license="MIT",
    install="docker build -f bench/adapters/docker/dbridge_mcp.Dockerfile (npm tarball)",
    command=(
        "docker run -i --rm --network container:<dbms> -e DBRIDGE_CONFIG -e DBRIDGE_DB_PATH"
        f" -v bench/adapters/config:/config:ro [-v <world dir>:/data:ro] {IMAGE}"
    ),
    tool=TOOL,
    arguments=ARGUMENT,
)
_SCHEMES = {"postgres": "postgresql", "mysql": "mysql"}


def url(db: Database, folder: str = "/data") -> str:
    """Return the connection string as its README spells it, seen from the sidecar."""
    if db.path is not None:
        return f"{folder}/{db.path.name}"
    where = f"{db.user}:{db.password}@localhost:{db.inner_port}/{db.name}"
    return f"{_SCHEMES[db.dialect]}://{where}"


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001 -- MCP flag
    """Read an answer: ``{"rowCount": n, "rows": [{...}], ...}``; anything else is a refusal."""
    if is_error:
        return REFUSED, None
    try:
        answer = json.loads(text)
    except json.JSONDecodeError:
        return REFUSED, None  # a guard refusal is a sentence
    rows = dict_rows(answer.get("rows")) if isinstance(answer, dict) else None
    return (REFUSED, None) if rows is None else (ANSWERED, rows)


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start the tool beside ``db``; SQLite is mounted read-only under ``/data``."""
    image = launch.ensure_image(IMAGE, dockerfile="dbridge_mcp.Dockerfile")
    mounts = {launch.CONFIG: "/config:ro"}
    if db.path is not None:
        mounts[db.path.parent] = "/data:ro"
    env = {"DBRIDGE_CONFIG": "/config/dbridge_mcp.json", "DBRIDGE_DB_PATH": url(db)}
    params = launch.container(image, db, env, mounts, [])
    arguments = lambda sql: {ARGUMENT: sql}  # noqa: E731
    return StdioAdapter(INFO, db.dialect, params, (arguments, parse), workdir=workdir)
