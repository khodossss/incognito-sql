"""sql-safe-mcp: an allowlisted SELECT subset; configured columns come back as tokens.

Published package ``sql-safe-mcp`` 1.5.2 (PyPI), run in a container of ours that adds the
ODBC driver its README requires for SQL Server. Config: ``config/sql_safe_mcp.<dbms>.yaml``.
"""

import base64
import json
from pathlib import Path

from bench.adapters import launch
from bench.adapters.base import ANSWERED, REFUSED, Info, Rows
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

IMAGE = "bench-sql-safe-mcp:1.5.2"
DIALECTS = ("mysql", "tsql")
INFO = Info(
    name="sql-safe-mcp",
    mechanism="SELECT-subset allowlist; listed columns as authenticated tokens",
    rung=4,
    version="1.5.2 (PyPI); docs read at repo SHA 9dd2a69",
    source="https://github.com/proprock/sql-safe-mcp",
    license="MIT",
    install=(
        "docker build -f bench/adapters/docker/sql_safe_mcp.Dockerfile"
        " (pip install sql-safe-mcp==1.5.2)"
    ),
    command=(
        "docker run -i --rm --network container:<dbms> -e BENCH_SQL_URL -e BENCH_PII_KEY"
        f" -v bench/adapters/config:/config:ro {IMAGE} --config /config/sql_safe_mcp.<dbms>.yaml"
    ),
    tool="execute_sql",
    arguments="server, database, sql",
)
_KEY = base64.b64encode(bytes(range(32))).decode()  # the alias key: a fixed bench secret
_DRIVER = "driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes"


def url(db: Database) -> str:
    """Return the connection URL as the tool's README spells it, seen from the sidecar."""
    where = f"{db.user}:{db.password}@localhost:{db.inner_port}/{db.name}"
    if db.dialect == "tsql":
        return f"mssql+pyodbc://{where}?{_DRIVER}"
    return f"mysql+pymysql://{where}"


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001 -- MCP flag
    """Read an answer: an error result is a refusal, else ``{"columns", "rows"}``."""
    if is_error:
        return REFUSED, None
    rows = json.loads(text).get("rows")
    return ANSWERED, rows if isinstance(rows, list) else None


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start the tool beside ``db``."""
    image = launch.ensure_image(IMAGE, dockerfile="sql_safe_mcp.Dockerfile")
    env = {"BENCH_SQL_URL": url(db), "BENCH_PII_KEY": _KEY}
    config = f"/config/sql_safe_mcp.{db.dialect}.yaml"
    params = launch.container(image, db, env, {launch.CONFIG: "/config:ro"}, ["--config", config])
    arguments = lambda sql: {"server": "bench", "database": db.name, "sql": sql}  # noqa: E731
    return StdioAdapter(INFO, db.dialect, params, (arguments, parse), workdir=workdir)
