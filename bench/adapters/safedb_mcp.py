"""safedb-mcp: a table allowlist, projection checks, and masks applied to returned columns.

The npm release ``@safedb/safedb-mcp`` 0.5.0 ships a Postgres-only build (its config
schema rejects ``database.type``); the repository at the pinned SHA adds MySQL and
SQLite, so the image is built from the repository's own Dockerfile at that SHA. Config:
``config/safedb_mcp.<dbms>.yaml``; it writes its JSONL audit log, which is scanned too.
"""

import json
from pathlib import Path

from bench.adapters import launch
from bench.adapters.base import ANSWERED, REFUSED, Info, Rows, dict_rows
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

REPO = "https://github.com/narekmalk/safedb-mcp"
SHA = "dab5ab01b93f26586184fde3c00f41378318cf79"
IMAGE = f"bench-safedb-mcp:{SHA[:7]}"
DIALECTS = ("postgres", "mysql", "sqlite")
INFO = Info(
    name="safedb-mcp",
    mechanism="table allowlist and projection checks; masks on returned columns",
    rung=2,
    version=f"repo SHA {SHA[:7]} (package.json 0.5.0)",
    source=REPO,
    license="MIT",
    install=f"git clone {REPO} && git checkout {SHA[:7]} && docker build -t {IMAGE} .",
    command=(
        "docker run -i --rm --network container:<dbms> -e SAFEDB_URL"
        f" -v bench/adapters/config:/config:ro -v <work>:/audit [-v <world dir>:/data:ro] {IMAGE}"
        " --config /config/safedb_mcp.<dbms>.yaml"
    ),
    tool="run_readonly_query",
    arguments="query",
)


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001 -- MCP flag
    """Read an answer: ``{"ok": true, "data": {"rows": [...]}}``, else a refusal."""
    answer = json.loads(text)
    if is_error or not answer.get("ok"):
        return REFUSED, None
    return ANSWERED, dict_rows(answer.get("data", {}).get("rows"))


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start the tool beside ``db``; SQLite is mounted read-only as ``/data/world.sqlite``."""
    image = launch.ensure_image(IMAGE, repo=REPO, sha=SHA)
    mounts = {launch.CONFIG: "/config:ro", workdir: "/audit"}
    if db.path is not None:
        mounts[db.path.parent] = "/data:ro"
    scheme = {"postgres": "postgres", "mysql": "mysql"}.get(db.dialect, "")
    where = f"{db.user}:{db.password}@localhost:{db.inner_port}/{db.name}"
    env = {"SAFEDB_URL": f"{scheme}://{where}"} if scheme else {}
    config = f"/config/safedb_mcp.{db.dialect}.yaml"
    params = launch.container(image, db, env, mounts, ["--config", config])
    arguments = lambda sql: {"query": sql}  # noqa: E731
    audit = workdir / "safedb-audit.jsonl"
    return StdioAdapter(INFO, db.dialect, params, (arguments, parse), workdir=workdir, audit=audit)
