"""keeper: results masked by column identity, the server's (table OID, attnum) of each column.

Its release binary 0.0.7, checked against the release checksums, in a Linux container of
ours (it does not run on Windows). The container registers the world's connection (its read
DSN) with our catalog (``config/keeper/catalog.yaml``), as its README's "Set up a
connection" does, then serves ``keeper mcp``. Each session states its intent first (0.0.7
requires it); every query names the connection id, which the container writes to the work
directory. Postgres only: the 0.0.7 release connects to nothing else.
"""

import json
from functools import partial
from pathlib import Path
from typing import Any

from bench.adapters import launch
from bench.adapters.base import ANSWERED, REFUSED, Info, Rows
from bench.adapters.mcp_stdio import QUERY_S, StdioAdapter
from bench.dbms import Database

VERSION, TAG_SHA = "0.0.7", "6a2ff518afb7774b27fe5a5abb6086216cedb149"
IMAGE = f"bench-keeper:{VERSION}"
DIALECTS = ("postgres",)
INFO = Info(
    name="keeper",
    mechanism="masks by column identity (table OID, attnum); identifiers as keyed tokens",
    rung=4,
    version=f"release {VERSION} (tag commit {TAG_SHA[:7]}); docs read at repo SHA c898050",
    source="https://github.com/mtch3n/keeper",
    license="MIT",
    install=(
        "docker build -f bench/adapters/docker/keeper.Dockerfile"
        f" (release keeper_{VERSION}_linux_amd64, SHA256 checked)"
    ),
    command=(
        "docker run -i --rm --network container:<postgres> -e KEEPER_MASTER_KEY -e KEEPER_DSN"
        f" -v bench/adapters/config:/config:ro -v <work>:/work {IMAGE}"
        " (keeper connection add --dsn ... --catalog ...; keeper mcp)"
    ),
    tool="query",
    arguments="connection_id, sql",
)
INTENT = "answer questions about the bench world"
_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="  # 32 bytes: a fixed bench master key


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001 -- MCP flag
    """Read an answer: ``{"rows", "columns", ...}``; an error or a pending ticket is a refusal."""
    if is_error:
        return REFUSED, None
    answer = json.loads(text)
    if answer.get("ticket"):
        return REFUSED, None  # waits for a human: the model gets no rows
    rows = answer.get("rows") or []
    return ANSWERED, rows if isinstance(rows, list) else None


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start the tool beside ``db``; it reaches Postgres on ``localhost``."""
    image = launch.ensure_image(IMAGE, dockerfile="keeper.Dockerfile")
    where = f"{db.user}:{db.password}@localhost:{db.inner_port}/{db.name}"
    env = {"KEEPER_MASTER_KEY": _KEY, "KEEPER_DSN": f"postgres://{where}?sslmode=disable"}
    mounts = {launch.CONFIG: "/config:ro", workdir: "/work"}
    params = launch.container(image, db, env, mounts, [])
    connection = workdir / "connection_id"

    def arguments(sql: str) -> dict[str, object]:
        given = connection.read_text("utf-8").strip() if connection.exists() else ""
        return {"connection_id": given, "sql": sql}

    return KeeperAdapter(INFO, db.dialect, params, (arguments, parse), workdir=workdir)


class KeeperAdapter(StdioAdapter):
    """A keeper session: it states its intent first, which 0.0.7 requires before any query."""

    def _connect(self) -> dict[str, dict[str, Any]]:
        tools = super()._connect()
        intent = partial(self._client.call_tool, "set_session_intent", {"intent": INTENT}, QUERY_S)
        self._portal.call(intent)
        return tools
