"""sanitized-db-mcp: an AST rewrite; columns not on the allowlist become placeholders.

Published image ``ghcr.io/ruminaider/sanitized-db-mcp`` (its README, "Docker (pre-built
image)"), pinned by digest. The PyPI release 0.2.0 does not start against the current MCP
SDK (``ImportError: request_ctx``), so the image is what runs. Postgres only. The image
requires SSL unless the URL names ``localhost``, so it runs as a sidecar of the Postgres
container and reaches it on ``localhost``. Config: ``config/sanitized_db_mcp.yaml``.
"""

import json
from pathlib import Path

from bench.adapters import launch
from bench.adapters.base import ANSWERED, REFUSED, Info, Rows, dict_rows
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database

DIGEST = "sha256:6527dcfafc0790476af218d4f1cf369bed89c923792b26af58815587a66d60fe"
IMAGE = f"ghcr.io/ruminaider/sanitized-db-mcp@{DIGEST}"
DIALECTS = ("postgres",)
INFO = Info(
    name="sanitized-db-mcp",
    mechanism="AST rewrite; columns off the allowlist become placeholders",
    rung=3,
    version="image 0.2.0, revision 876c931 (label), digest " + DIGEST[:19],
    source="https://github.com/evvy-bio/sanitized-db-mcp",
    license="MIT",
    install=f"docker pull {IMAGE}",
    command=(
        "docker run -i --rm --network container:<postgres> -e ALLOWLIST_PATH -e DATABASE_URL"
        f" -v bench/adapters/config:/config:ro {IMAGE}"
    ),
    tool="query",
    arguments="sql",
)


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001 -- MCP flag
    """``Error: ...`` is a refusal; an answer is a ``/* header */`` and a JSON row list."""
    if is_error or text.startswith("Error"):
        return REFUSED, None
    body = text.split("*/", 1)[-1]
    return ANSWERED, dict_rows(json.loads(body))


def open_adapter(db: Database, workdir: Path) -> StdioAdapter:
    """Start the tool beside ``db``."""
    image = launch.ensure_image(IMAGE)
    env = {
        "ALLOWLIST_PATH": "/config/sanitized_db_mcp.yaml",
        "DATABASE_URL": f"postgresql://{db.user}:{db.password}@localhost:{db.inner_port}/{db.name}",
    }
    params = launch.container(image, db, env, {launch.CONFIG: "/config:ro"}, [])
    arguments = lambda sql: {"sql": sql}  # noqa: E731
    return StdioAdapter(INFO, db.dialect, params, (arguments, parse), workdir=workdir)
