"""mcp-db-results-anonymizer: result columns classified, then replaced by Faker pseudonyms.

Classification: per-column sensitivity levels, column-name patterns, SQL lineage
(sqlglot) to output columns, and a scan of returned values. Published image
``dnjfr/mcp-db-results-anonymizer`` 1.0.1 pinned by digest, plus the ``mysql`` extra its
docs name, in a Dockerfile of ours (``docker/db_results_anonymizer.Dockerfile``). It runs
over stdio (``MCP_TRANSPORT=stdio``, its dev mode); its secured mode serves the same
tools over SSE with a bearer token and a rate limit. Mappings are ephemeral (its default):
pseudonyms hold within one query only. Config: ``config/db_results_anonymizer.yaml``.
Its log (stderr) names each query; it is scanned too. SQL Server, which it lists, does not
run: its connector sets ``readonly`` on each pyodbc connection, an attribute pyodbc
connections lack, so every query fails (observed with pyodbc 5.2.0 and ODBC Driver 18).
"""

import json
from pathlib import Path

from bench.adapters import launch
from bench.adapters.base import ANSWERED, REFUSED, Info, NotRunError, Rows
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

VERSION = "1.0.1"
IMAGE = f"bench-db-results-anonymizer:{VERSION}"
DIALECTS = ("postgres", "mysql", "tsql")
_TYPES = {"postgres": "postgresql", "mysql": "mysql", "tsql": "mssql"}
_NO_TSQL = "1.0.1 sets pyodbc Connection.readonly, which pyodbc lacks: every query fails"
INFO = Info(
    name="mcp-db-results-anonymizer",
    mechanism="columns classified by level, name, lineage and value scan; Faker pseudonyms",
    rung=2,
    version=f"{VERSION} (image digest sha256:8094a8f; repo tag v{VERSION}, SHA 6aa6ae3)",
    source="https://github.com/dnjfr/mcp-db-results-anonymizer",
    license="Apache-2.0",
    install=(
        "docker build -f bench/adapters/docker/db_results_anonymizer.Dockerfile"
        f" (dnjfr/mcp-db-results-anonymizer:{VERSION} + its mysql extra)"
    ),
    command=(
        "docker run -i --rm --network container:<dbms> -e MCP_TRANSPORT=stdio -e MCP_ANON_CONFIG"
        " -e BENCH_DB_TYPE -e BENCH_DB_PORT -e BENCH_DB_PASSWORD"
        f" -v bench/adapters/config:/config:ro {IMAGE}"
    ),
    tool="querySql",
    arguments="database, query",
)


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001 -- MCP flag
    """Read an answer: ``{"error": ...}`` is a refusal, else ``{"columns", "rows"}``."""
    answer = json.loads(text)
    if is_error or "error" in answer:
        return REFUSED, None
    rows = answer.get("rows")
    return ANSWERED, rows if isinstance(rows, list) else None


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start the tool beside ``db``; SQL Server gets a fixed reason instead."""
    if db.dialect == "tsql":
        raise NotRunError(_NO_TSQL)
    image = launch.ensure_image(IMAGE, dockerfile="db_results_anonymizer.Dockerfile")
    env = {
        "MCP_TRANSPORT": "stdio",
        "MCP_ANON_CONFIG": "/config/db_results_anonymizer.yaml",
        "BENCH_DB_TYPE": _TYPES[db.dialect],
        "BENCH_DB_PORT": str(db.inner_port),
        "BENCH_DB_PASSWORD": db.password,
    }
    params = launch.container(image, db, env, {launch.CONFIG: "/config:ro"}, [])
    arguments = lambda sql: {"database": "world", "query": sql}  # noqa: E731
    return StdioAdapter(INFO, db.dialect, params, (arguments, parse), workdir=workdir)
