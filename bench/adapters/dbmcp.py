"""dbmcp: SQL validation for read-only use; values redacted by entity regexes and NER.

Published image ``ghcr.io/haymon-ai/dbmcp`` 0.15.2 pinned by digest, plus the NER model
its docs recommend, in a Dockerfile of ours (``docker/dbmcp.Dockerfile``). The image's own
``stdio`` command runs it. Release 0.15.2 reads its settings from ``DB_*`` and ``PII_*``
variables (the ``DBMCP_*`` names and ``--config`` file of its current README came after).
Redaction is off by default; ``PII`` below turns it on as its docs at the tag describe:
every built-in category, the default ``replace`` operator, and the NER pass. It keeps no
per-column setting and no audit log; read-only mode (its default) hides the write tools.
"""

import json
from pathlib import Path

from bench.adapters import launch
from bench.adapters.base import ANSWERED, REFUSED, Info, Rows
from bench.adapters.keyorder import object_rows
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

VERSION = "0.15.2"
IMAGE = f"bench-dbmcp:{VERSION}-ner"
DIALECTS = ("postgres", "mysql", "sqlite")
PII = {
    "PII_ENABLE": "true",
    "PII_OPERATOR": "replace",
    "PII_NER_ENABLE": "true",
    "PII_NER_MODEL": "/models/bert-ner",
}
INFO = Info(
    name="dbmcp",
    mechanism="read-only SQL validation; values redacted by entity regexes and NER",
    rung=1,
    version=f"{VERSION} (image digest sha256:2e3fbf0); NER optimum/bert-base-NER b0a40a0",
    source="https://github.com/haymon-ai/dbmcp",
    license="MIT",
    install=(
        "docker build -f bench/adapters/docker/dbmcp.Dockerfile"
        f" (ghcr.io/haymon-ai/dbmcp:{VERSION} + the NER model)"
    ),
    command=(
        "docker run -i --rm --network container:<dbms> -e DB_BACKEND -e DB_HOST -e DB_PORT"
        " -e DB_USER -e DB_PASSWORD -e DB_NAME -e PII_ENABLE=true -e PII_OPERATOR=replace"
        " -e PII_NER_ENABLE=true -e PII_NER_MODEL=/models/bert-ner"
        f" [-v <world dir>:/data:ro] {IMAGE} stdio"
    ),
    tool="readQuery",
    arguments="query",
)


def parse(
    text: str,
    is_error: bool,  # noqa: FBT001 -- MCP flag
    sql: str = "",
    dialect: str = "postgres",
) -> tuple[str, Rows | None]:
    """Read an answer: an error result is a refusal, else ``{"rows": [{...}, ...]}``.

    Its row objects come with sorted keys; ``sql`` puts them back in select order.
    """
    if is_error:
        return REFUSED, None
    return ANSWERED, object_rows(json.loads(text).get("rows"), sql, dialect)


def environment(db: Database) -> dict[str, str]:
    """Return the variables that reach ``db`` from the sidecar and turn redaction on."""
    if db.path is not None:
        return {"DB_BACKEND": "sqlite", "DB_NAME": f"/data/{db.path.name}", **PII}
    return {
        "DB_BACKEND": db.dialect,
        "DB_HOST": "localhost",
        "DB_PORT": str(db.inner_port),
        "DB_USER": db.user,
        "DB_PASSWORD": db.password,
        "DB_NAME": db.name,
        **PII,
    }


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start the tool beside ``db``; SQLite is mounted read-only under ``/data``."""
    image = launch.ensure_image(IMAGE, dockerfile="dbmcp.Dockerfile")
    mounts = {db.path.parent: "/data:ro"} if db.path is not None else {}
    params = launch.container(image, db, environment(db), mounts, ["stdio"])
    sent = [""]  # the query in flight, to order the keys of its answer

    def arguments(sql: str) -> dict[str, object]:
        sent[0] = sql
        return {"query": sql}

    def read(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001
        return parse(text, is_error, sent[0], db.dialect)

    return StdioAdapter(INFO, db.dialect, params, (arguments, read), workdir=workdir)
