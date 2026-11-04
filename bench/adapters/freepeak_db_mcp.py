"""db-mcp-server (FreePeak): output masks by column-name regex and by value shape.

Built from its repository at the release tag v1.14.0 with the repository's own
Dockerfile, the release that ships ``mask_pii`` (content-shape redaction); its README
recommends a local stdio build of an audited revision, which the image's binary is.
It runs ``/app/server -t stdio -c <config>``. Config: ``config/freepeak_db_mcp.<dbms>.json``
(``masking_rules`` by output column name plus ``"mask_pii": true``). Its JSONL audit log
is not turned on: set by ``DB_MCP_AUDIT_LOG``, as its README says, it deadlocks the first
query in v1.14.0 (the lazy ``sync.Once`` opener calls ``Once.Do`` on itself).
"""

from pathlib import Path

from bench.adapters import launch
from bench.adapters.base import ANSWERED, REFUSED, Info, Rows
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

REPO = "https://github.com/FreePeak/db-mcp-server"
TAG = "v1.14.0"
SHA = "1b79050b2ce2c4edf740e1b17de85aae741511b1"
IMAGE = f"bench-freepeak-db-mcp:{TAG}"
DIALECTS = ("postgres", "mysql", "sqlite")
INFO = Info(
    name="db-mcp-server",
    mechanism="output masked by column-name regex rules and by value shape (mask_pii)",
    rung=1,
    version=f"{TAG} (repo SHA {SHA[:7]})",
    source=REPO,
    license="MIT",
    install=f"git clone {REPO} && git checkout {TAG} && docker build -t {IMAGE} .",
    command=(
        "docker run -i --rm --network container:<dbms> -e DB_MCP_PASSWORD"
        f" -v bench/adapters/config:/config:ro [-v <world dir>:/data:ro] {IMAGE}"
        " /app/server -t stdio -c /config/freepeak_db_mcp.<dbms>.json"
    ),
    tool="query_world",
    arguments="query",
)
_NULL = "NULL"


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001 -- MCP flag
    """Read an answer: a header line, a dashed rule, tab-separated rows, a blank line."""
    if is_error or not text.startswith("Results:"):
        return REFUSED, None
    lines = text.split("\n")
    rule = next(i for i, line in enumerate(lines) if line.startswith("-" * 10))
    body = lines[rule + 1 : lines.index("", rule + 1)]
    return ANSWERED, [[None if v == _NULL else v for v in line.split("\t")] for line in body]


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start the tool beside ``db``; SQLite is mounted read-only as ``/data/world.sqlite``."""
    image = launch.ensure_image(IMAGE, repo=REPO, sha=SHA)
    mounts = {launch.CONFIG: "/config:ro"}
    if db.path is not None:
        mounts[db.path.parent] = "/data:ro"
    env = {"DB_MCP_PASSWORD": db.password}
    config = f"/config/freepeak_db_mcp.{db.dialect}.json"
    run = ["/app/server", "-t", "stdio", "-c", config]
    params = launch.container(image, db, env, mounts, run)
    arguments = lambda sql: {"query": sql}  # noqa: E731
    return StdioAdapter(INFO, db.dialect, params, (arguments, parse), workdir=workdir)
