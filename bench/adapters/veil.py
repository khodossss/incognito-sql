"""veil: values learned from the database are replaced by consistent pseudonyms in the output.

Published package ``veil-proxy`` 0.3.2 (PyPI), run in a container of ours. Its database tool
``veil mcp-db`` needs veil seeded first, as its README's "Quick start" and "Data sources"
do it (``veil seed SOURCE``, ``veil seed --schema DIR``), so the container seeds from the
world, with our column declaration as a Prisma schema (``config/veil/schema.prisma``), and
then serves the tool. A pseudonym inside a string literal is bound as the real value.
Keys come from the environment, as its README offers for containers.
"""

import base64
from pathlib import Path

from bench.adapters import launch
from bench.adapters.base import ANSWERED, REFUSED, Info, Rows
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

SHA = "d4476c4975b118a1c8f1c15610f109f9455f793b"
IMAGE = "bench-veil:0.3.2"
DIALECTS = ("postgres", "mysql", "sqlite", "tsql")
INFO = Info(
    name="veil",
    mechanism="values seeded from the data become consistent pseudonyms in any output",
    rung=3,
    version=f"0.3.2 (PyPI); docs read at repo SHA {SHA[:7]}",
    source="https://github.com/lemonadesaltbagel/veil",
    license="Apache-2.0",
    install="docker build -f bench/adapters/docker/veil.Dockerfile (pip install veil-proxy==0.3.2)",
    command=(
        "docker run -i --rm --network container:<dbms> -e VEIL_DB -e VEIL_VAULT_KEY"
        f" -e VEIL_TOKEN_SECRET -v bench/adapters/config:/config:ro [-v <world dir>:/data:ro]"
        f" {IMAGE} (veil seed --schema /config/veil $VEIL_DB; veil mcp-db $VEIL_DB)"
    ),
    tool="query",
    arguments="sql",
)
# Fixed bench secrets: the vault key and the pseudonym secret, 32 bytes each.
KEYS = {
    "VEIL_VAULT_KEY": base64.b64encode(bytes(range(32))).decode(),
    "VEIL_TOKEN_SECRET": base64.b64encode(bytes(range(32, 64))).decode(),
}
_SCHEMES = {"postgres": "postgresql", "mysql": "mysql", "tsql": "mssql"}
_NULL = "NULL"


def url(db: Database) -> str:
    """Return the source as its README spells it, seen from the sidecar."""
    if db.path is not None:
        return f"/data/{db.path.name}"
    where = f"{db.user}:{db.password}@localhost:{db.inner_port}/{db.name}"
    return f"{_SCHEMES[db.dialect]}://{where}"


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001 -- MCP flag
    """Read an answer: a tab-separated header, rows and a ``(N rows)`` line; else a refusal."""
    if is_error:
        return REFUSED, None
    lines = text.split("\n")
    body = lines[1:-1] if lines[-1].startswith("(") else lines[1:]
    return ANSWERED, [[None if c == _NULL else c for c in line.split("\t")] for line in body]


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start the tool beside ``db``; SQLite is mounted read-only under ``/data``."""
    image = launch.ensure_image(IMAGE, dockerfile="veil.Dockerfile")
    mounts = {launch.CONFIG: "/config:ro"}
    if db.path is not None:
        mounts[db.path.parent] = "/data:ro"
    env = {"VEIL_DB": url(db), **KEYS}
    params = launch.container(image, db, env, mounts, [])
    arguments = lambda sql: {"sql": sql}  # noqa: E731
    return StdioAdapter(INFO, db.dialect, params, (arguments, parse), workdir=workdir)
