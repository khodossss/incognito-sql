"""The project server's MCP surface: the setup tools beside `query` and `describe`."""

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from incognito_sql.mcp.server import DESCRIBE_DESCRIPTION, QUERY_DESCRIPTION, instructions
from incognito_sql.project.tools import Tools
from incognito_sql.project.words import CARDS_TEXT, DEMO_TEXT, DRAFT_TEXT, STATUS_TEXT

NAME = "incognito-sql"
_READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
_WRITES = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)


def build_server(tools: Tools, connection_id: str) -> MCPServer:
    """Create the project server over ``tools``; queries count against ``connection_id``."""
    server: MCPServer = MCPServer(name=NAME, instructions=instructions(), log_level="WARNING")

    def setup_status() -> str:
        return tools.status()

    def create_demo() -> str:
        return tools.create_demo()

    def draft_declaration(
        dialect: str, dsn_env: str | None = None, database_file: str | None = None
    ) -> str:
        return tools.draft(dialect, dsn_env, database_file)

    def open_cards() -> str:
        return tools.open_cards()

    def query(sql: str) -> str:
        return tools.query(sql, connection_id)

    def describe() -> str:
        return tools.describe()

    for fn, name, text, notes in (
        (setup_status, "setup_status", STATUS_TEXT, _READ_ONLY),
        (create_demo, "create_demo", DEMO_TEXT, _WRITES),
        (draft_declaration, "draft_declaration", DRAFT_TEXT, _WRITES),
        (open_cards, "open_cards", CARDS_TEXT, _WRITES),
        (query, "query", QUERY_DESCRIPTION, _READ_ONLY),
        (describe, "describe", DESCRIBE_DESCRIPTION, _READ_ONLY),
    ):
        server.add_tool(fn, name=name, description=text, annotations=notes, structured_output=False)
    return server
