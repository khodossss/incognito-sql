"""DBHub: the plain database MCP server that the proxy-style competitors are paired with.

gate protects a database MCP server it does not ship: it rewrites the answers of
whatever MCP server it wraps. It is paired with DBHub (``@bytebase/dbhub``, npm, MIT):
one widely used open server with no masking of its own, one SQL tool (``execute_sql``)
and one connection URL for Postgres, MySQL, SQL Server and SQLite. It connects as the bench reader.
"""

import json

from bench.adapters.base import ANSWERED, REFUSED, Rows, dict_rows
from bench.dbms import Database

VERSION = "1.5.0"
SOURCE = "https://github.com/bytebase/dbhub"
TOOL, ARGUMENT = "execute_sql", "sql"
DIALECTS = ("postgres", "mysql", "tsql", "sqlite")
_SCHEMES = {"postgres": "postgres", "mysql": "mysql", "tsql": "sqlserver"}
SQLITE_DIR = "/data"  # where a SQLite world is mounted read-only


def dsn(db: Database, port: int = 0) -> str:
    """Return DBHub's DSN for ``db`` as seen from a sidecar; ``port`` overrides the DBMS's."""
    if db.path is not None:
        return f"sqlite://{SQLITE_DIR}/{db.path.name}"
    where = f"{db.user}:{db.password}@localhost:{port or db.inner_port}/{db.name}"
    return f"{_SCHEMES[db.dialect]}://{where}?sslmode=disable"


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001 -- MCP flag
    """Read an answer: ``{"success": true, "data": {"statements": [{"rows": [...]}]}}``.

    Anything else is a refusal; of several statements, the last one's rows are the answer.
    """
    answer = json.loads(text)
    if is_error or not answer.get("success"):
        return REFUSED, None
    statements = answer.get("data", {}).get("statements") or [{}]
    return ANSWERED, dict_rows(statements[-1].get("rows"))
