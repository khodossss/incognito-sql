"""JanuScope: an MCP policy proxy; a keyword SQL guard and answers redacted by key and regex.

The npm release 0.5.0 in a container of ours, each DBMS with the upstream server of its
bundled lens: Postgres MCP Pro (``postgres-crystaldba``), ``@benborla29/mcp-server-mysql``
(``mysql-benborla29``) and ``mcp-sqlite`` (``sqlite-panasenco``). Its bundled SQL Server
lens wraps Data API builder, which takes no SQL, so SQL Server is not run. Config:
``config/januscope.<dbms>.yaml``; its JSONL audit log is scanned too.
"""

import dataclasses
from pathlib import Path

from bench.adapters import launch
from bench.adapters.base import Info
from bench.adapters.januscope_answers import parse
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

VERSION = "0.5.0"
IMAGE = f"bench-januscope:{VERSION}"
DIALECTS = ("postgres", "mysql", "sqlite")
TOOLS = {"postgres": "execute_sql", "mysql": "mysql_query", "sqlite": "sqlite_execute"}
INFO = Info(
    name="januscope",
    mechanism="MCP policy proxy; keyword SQL guard; answers redacted by key and regexes",
    rung=1,
    version=(
        f"{VERSION} (npm); upstreams: postgres-mcp 0.3.0 (image), "
        "@benborla29/mcp-server-mysql 2.0.9 (npm), mcp-sqlite 0.3.2 (PyPI)"
    ),
    source="https://github.com/giancarloerra/JanuScope",
    license="AGPL-3.0-only (run, not copied); upstreams MIT",
    install="docker build -f bench/adapters/docker/januscope.Dockerfile",
    command=(
        "docker run -i --rm --network container:<dbms> -e <upstream connection>"
        f" -v bench/adapters/config:/config:ro -v <work>:/audit [-v <world dir>:/data:ro] {IMAGE}"
        " --config /config/januscope.<dbms>.yaml"
    ),
    tool="execute_sql | mysql_query | sqlite_execute",
    arguments="sql",
)


def connection(db: Database) -> dict[str, str]:
    """Return the environment each lens's upstream reads, as seen from the sidecar."""
    if db.dialect == "sqlite" and db.path is not None:
        return {"SQLITE_DB_PATH": f"/data/{db.path.name}"}
    if db.dialect == "mysql":
        return {
            "MYSQL_HOST": "127.0.0.1",
            "MYSQL_PORT": str(db.inner_port),
            "MYSQL_USER": db.user,
            "MYSQL_PASS": db.password,
            "MYSQL_DB": db.name,
        }
    where = f"{db.user}:{db.password}@localhost:{db.inner_port}/{db.name}"
    return {"DATABASE_URI": f"postgresql://{where}"}


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start JanuScope and its lens's upstream beside ``db``."""
    image = launch.ensure_image(IMAGE, dockerfile="januscope.Dockerfile")
    mounts = {launch.CONFIG: "/config:ro", workdir: "/audit"}
    if db.path is not None:
        mounts[db.path.parent] = "/data:ro"
    env = {**connection(db), "JANUSCOPE_QUIET": "1"}
    config = f"/config/januscope.{db.dialect}.yaml"
    params = launch.container(image, db, env, mounts, ["--config", config])
    info = dataclasses.replace(INFO, tool=TOOLS[db.dialect])
    arguments = lambda sql: {"sql": sql}  # noqa: E731
    audit = workdir / "januscope-audit.jsonl"
    return StdioAdapter(info, db.dialect, params, (arguments, parse), workdir=workdir, audit=audit)
