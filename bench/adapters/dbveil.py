"""dbveil: a Postgres parser guard (read only) and answers redacted by column name and regexes.

The PyPI release 0.2.0 (``veil up``) in a container of ours, without its optional NER and
LLM extras. Postgres only (asyncpg, libpg_query). Every query runs in a READ ONLY
transaction; column rules rewrite the answer's columns by name, built-in regexes rewrite
emails, phones, cards and SSNs in any string cell. Its JSONL audit log (SQL text and
verdicts) is written to the work directory and scanned. Config: ``config/dbveil.yaml``.
"""

import json
from pathlib import Path

from bench.adapters import launch
from bench.adapters.base import ANSWERED, REFUSED, Info, Rows
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

VERSION = "0.2.0"
IMAGE = f"bench-dbveil:{VERSION}"
DIALECTS = ("postgres",)
INFO = Info(
    name="dbveil",
    mechanism="Postgres parser guard (read only); answers redacted by column name and regexes",
    rung=1,
    version=f"{VERSION} (PyPI; repo tag v{VERSION})",
    source="https://github.com/mathu97/dbveil",
    license="MIT",
    install=f"docker build -f bench/adapters/docker/dbveil.Dockerfile (dbveil=={VERSION})",
    command=(
        "docker run -i --rm --network container:<postgres> -e VEIL_CONFIG -e VEIL_DATABASE_URL"
        f" -v bench/adapters/config:/config:ro -v <work>:/audit {IMAGE} (veil up)"
    ),
    tool="query",
    arguments="sql",
)


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001 -- MCP flag
    """Read an answer: ``{"status": "ok", "rows": [[...]]}``; blocked or error is a refusal."""
    answer = json.loads(text)
    if is_error or answer.get("status") != "ok":
        return REFUSED, None
    rows = answer.get("rows")
    return ANSWERED, rows if isinstance(rows, list) else None


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start dbveil beside ``db``; it reaches Postgres on ``localhost``."""
    image = launch.ensure_image(IMAGE, dockerfile="dbveil.Dockerfile")
    where = f"{db.user}:{db.password}@localhost:{db.inner_port}/{db.name}"
    env = {"VEIL_CONFIG": "/config/dbveil.yaml", "VEIL_DATABASE_URL": f"postgresql://{where}"}
    mounts = {launch.CONFIG: "/config:ro", workdir: "/audit"}
    params = launch.container(image, db, env, mounts, [])
    arguments = lambda sql: {"sql": sql}  # noqa: E731
    audit = workdir / "veil-audit.jsonl"
    return StdioAdapter(INFO, db.dialect, params, (arguments, parse), workdir=workdir, audit=audit)
