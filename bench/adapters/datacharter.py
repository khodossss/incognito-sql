"""DataCharter: DuckDB over the database; declared personal columns masked and unusable.

Published wheel ``datacharter`` 0.44.0 (PyPI), run in a container of ours as
``datacharter mcp`` over a workspace holding our ``charter.yaml``
(``config/datacharter.<dbms>.yaml``). Its ``pii`` columns reach the model as ``•••``,
also through any expression over them, and a query naming one in WHERE, JOIN, GROUP BY,
ORDER BY or a subquery is refused. Every source is attached to DuckDB, which runs the
query: the tool tells the model to use fully-qualified relation names (its ``query`` tool
and ``list_tables``) and names no SQL dialect, so a query goes as written, with the
world's unqualified tables qualified by the source name, as the model would write them.
"""

import json
from collections.abc import Iterable
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp
from sqlglot.errors import SqlglotError

from bench.adapters import launch
from bench.adapters.base import ANSWERED, REFUSED, Info, NotRunError, Rows
from bench.adapters.calls import Arguments
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

VERSION = "0.44.0"
IMAGE = f"bench-datacharter:{VERSION}"
DIALECTS = ("postgres", "mysql", "sqlite", "duckdb", "tsql")
SOURCE = "bench"  # the source name in our charters: the prefix of every relation
TOOL, ARGUMENT = "query", "sql"
INFO = Info(
    name="datacharter",
    mechanism=(
        "declared personal columns masked through any expression and refused in filters;"
        " table names qualified by its source, as it asks"
    ),
    rung=2,
    version=f"{VERSION} (PyPI)",
    source="https://github.com/datacharter/datacharter",
    license="Apache-2.0",
    install="docker build -f bench/adapters/docker/datacharter.Dockerfile (PyPI wheel)",
    command=(
        "docker run -i --rm --network container:<dbms> -e BENCH_DB_PASSWORD -e BENCH_DB_FILE"
        f" -v <work>:/ws [-v <world dir>:/data:ro] {IMAGE} (datacharter mcp /ws)"
    ),
    tool=TOOL,
    arguments=ARGUMENT,
)
_READ = {"tsql": "tsql"}
# sqlglot raises more than SqlglotError on odd input: such a query goes as written.
_UNREADABLE = (SqlglotError, ValueError, AttributeError, TypeError, RecursionError)


def qualify(sql: str, dialect: str, tables: Iterable[str]) -> str:
    """Prefix each unqualified name of ``tables`` with the source; leave the rest as written.

    The prefix goes in at the name's own position, so comments, spelling and literals of
    the query stay as they are; a CTE of the same name is left alone, and a query sqlglot
    cannot read goes unchanged.
    """
    names = {t.casefold() for t in tables}
    try:
        trees = sqlglot.parse(sql, read=_READ.get(dialect, dialect))
    except _UNREADABLE:
        return sql
    starts: set[int] = set()
    for tree in (t for t in trees if t is not None):
        ctes = {c.alias_or_name.casefold() for c in tree.find_all(exp.CTE)}
        for table in tree.find_all(exp.Table):
            name = table.name.casefold()
            if table.db or table.catalog or name in ctes or name not in names:
                continue
            start = table.this.meta.get("start") if table.this is not None else None
            if isinstance(start, int):
                starts.add(start)
    for start in sorted(starts, reverse=True):
        sql = f"{sql[:start]}{SOURCE}.{sql[start:]}"
    return sql


def arguments(dialect: str, known: Iterable[str]) -> Arguments:
    """Return the tool's arguments for a query: its tables qualified by the source."""
    names = list(known)

    def sent(sql: str) -> dict[str, object]:
        return {ARGUMENT: qualify(sql, dialect, names)}

    return sent


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001 -- MCP flag
    """Read an answer: ``{"columns": [...], "rows": [[...]], ...}``; an ``Error:`` is a refusal."""
    if is_error or text.startswith("Error"):
        return REFUSED, None
    rows = json.loads(text).get("rows")
    return (ANSWERED, rows) if isinstance(rows, list) else (REFUSED, None)


def charter(dialect: str) -> str:
    """Return our charter for ``dialect``."""
    return (launch.CONFIG / f"datacharter.{dialect}.yaml").read_text(encoding="utf-8")


def tables(text: str) -> list[str]:
    """Return the tables a charter lists for its source."""
    loaded = yaml.safe_load(text)
    return [str(t) for t in loaded["sources"][SOURCE]["tables"]]


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start the tool beside ``db`` over a workspace in ``workdir``.

    On SQL Server it does not run: its attach verifies the server's TLS certificate and
    takes no ``TrustServerCertificate`` (an mssql source reads host, port, database, user
    and password only), and the bench server's certificate is self-signed.
    """
    if db.dialect == "tsql":
        msg = "its SQL Server attach verifies the TLS certificate (no TrustServerCertificate)"
        raise NotRunError(msg)
    image = launch.ensure_image(IMAGE, dockerfile="datacharter.Dockerfile")
    text = charter(db.dialect)
    (workdir / "charter.yaml").write_text(text, encoding="utf-8")
    mounts = {workdir: "/ws"}
    env = {"BENCH_DB_PASSWORD": db.password, "BENCH_DB_FILE": ""}
    if db.path is not None:
        mounts[db.path.parent] = "/data:ro"
        env["BENCH_DB_FILE"] = f"/data/{db.path.name}"
    params = launch.container(image, db, env, mounts, ["/ws"])
    calls = (arguments(db.dialect, tables(text)), parse)
    return StdioAdapter(INFO, db.dialect, params, calls, workdir=workdir)
