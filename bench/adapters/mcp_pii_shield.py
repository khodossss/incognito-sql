"""mcp-pii-shield: a keyword guard on the SQL text; masks by column name and value regexes.

Built from its repository at the pinned commit, the latest code (the npm release 1.0.0
predates the repository's later hardening). The repository's own Dockerfile copies a
prebuilt ``dist/``, so the README's native build (``npm ci``, ``npm run build``) runs
first in a throwaway Node container; then that Dockerfile builds the image. It runs
``node dist/index.js --db-uri ...`` over stdio, as the README's "Direct Execution"
section starts it; the Dockerfile's ``TRANSPORT=sse`` default is set back to stdio.

It has no per-column configuration: masking keys on fixed column names (name, email,
phone, ...) and regexes, plus a name roster (the repository's own sample, which holds
no name of this world). It also offers ``unmask_text``, which returns raw values for
placeholders to the same agent; the benchmark sends SQL only and never calls it.
Postgres only.
"""

import json
from pathlib import Path

from bench.adapters import launch
from bench.adapters.base import ANSWERED, REFUSED, Info, Rows, dict_rows
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

REPO = "https://github.com/thegeekybeng/mcp-pii-shield"
SHA = "051534024a87207de8b71f0d68671c2ed6d7a4fd"
IMAGE = f"bench-mcp-pii-shield:{SHA[:7]}"
PREPARE = ("node:20-alpine", "npm ci && npm run build")
DIALECTS = ("postgres",)
INFO = Info(
    name="mcp-pii-shield",
    mechanism="keyword guard on SQL text; output masked by column name and regexes",
    rung=1,
    version=f"repo SHA {SHA[:7]} (package.json 1.0.0; npm 1.0.0 is older code)",
    source=REPO,
    license="MIT",
    install=(
        f"git clone {REPO} && git checkout {SHA[:7]} && npm ci && npm run build"
        f" (in {PREPARE[0]}) && docker build -t {IMAGE} ."
    ),
    command=(
        "docker run -i --rm --network container:<postgres> -e TRANSPORT=stdio"
        f" {IMAGE} node dist/index.js --db-uri postgresql://<reader>@localhost:5432/world"
    ),
    tool="run_secure_query",
    arguments="sql_query",
)


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001 -- MCP flag
    """Read an answer: an error result is a refusal, else a JSON list of row objects."""
    if is_error:
        return REFUSED, None
    return ANSWERED, dict_rows(json.loads(text))


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start the tool beside ``db``; it reaches Postgres on ``localhost``."""
    image = launch.ensure_image(IMAGE, repo=REPO, sha=SHA, prepare=PREPARE)
    uri = f"postgresql://{db.user}:{db.password}@localhost:{db.inner_port}/{db.name}"
    run = ["node", "dist/index.js", "--db-uri", uri]
    params = launch.container(image, db, {"TRANSPORT": "stdio"}, {}, run)
    arguments = lambda sql: {"sql_query": sql}  # noqa: E731
    return StdioAdapter(INFO, db.dialect, params, (arguments, parse), workdir=workdir)
