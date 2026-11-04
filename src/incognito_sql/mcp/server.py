"""The MCP surface: exactly two read-only tools, `query` and `describe`."""

import json
from importlib import resources

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from incognito_sql.core.pipeline import Gateway
from incognito_sql.mcp.refusals import explained

NAME = "incognito-sql"

QUERY_DESCRIPTION = """Run one read-only SQL SELECT and get the rows as JSON.

Identifier cells (names, phones, e-mails...) come back as links ending in a token \
`tk_...` (or as labels like `name_1` in labels mode): pseudonyms, not missing data. \
Same link = same value. To follow up on a value, compare an identifier column with the \
token: `WHERE full_name = 'tk_...'` or `IN ('tk_...', ...)`, or with a literal a human gave \
you. What an identifier column admits is listed by `describe` (identifier_operations): \
at most selected, grouped, counted with COUNT(DISTINCT), compared with = / IN, tested \
with IS NULL. Hidden columns exist but cannot be named. A refusal is \
{"error": <reason>, "sqlstate": ..., "retry": ..., "hint": ...}: `retry` is `rewrite` \
(fix the query yourself), `ask_user` (only the user can lift it) or `stop` (give up on \
this question); `hint` says why, the same for every refusal with that reason."""

DESCRIBE_DESCRIPTION = """Name the DBMS (write SQL in its dialect) and list the tables \
you can query: usable columns with their class (identifier, quasi, open) and the number \
of hidden columns per table. Hidden columns are counted, never named, and any query that \
mentions one is refused. `identifier_operations` lists what may be done with an \
identifier column; a table lists its own for a column that differs. A table of people \
names its `person_key`: link a row that holds it to the person's card."""

_READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


def instructions() -> str:
    """Return the server instructions sent to the client at connection time."""
    return resources.files("incognito_sql.mcp").joinpath("instructions.md").read_text("utf-8")


def build_server(gateway: Gateway, connection_id: str) -> MCPServer:
    """Create the server; every query is counted against ``connection_id``."""
    server: MCPServer = MCPServer(name=NAME, instructions=instructions(), log_level="WARNING")

    def query(sql: str) -> str:
        return json.dumps(explained(gateway.query(sql, connection_id)), ensure_ascii=False)

    def describe() -> str:
        return json.dumps(gateway.describe(), ensure_ascii=False)

    server.add_tool(
        query,
        name="query",
        description=QUERY_DESCRIPTION,
        annotations=_READ_ONLY,
        structured_output=False,
    )
    server.add_tool(
        describe,
        name="describe",
        description=DESCRIBE_DESCRIPTION,
        annotations=_READ_ONLY,
        structured_output=False,
    )
    return server
