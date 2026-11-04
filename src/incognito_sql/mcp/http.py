"""MCP over streamable HTTP on 127.0.0.1, reachable only with the service's bearer token."""

import hmac

import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

HOST = "127.0.0.1"
PATH = "/mcp"
UNAUTHORIZED = "unauthorized\n"


class BearerGate:
    """Answer 401 to any HTTP request without ``Authorization: Bearer <token>``.

    The check runs before the MCP app sees the request; the comparison takes
    constant time. Lifespan events pass through untouched.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        """Wrap ``app``; ``token`` is the only credential accepted."""
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass an authorized request (or a non-HTTP scope) on; refuse the rest."""
        if scope["type"] == "http":
            sent = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(sent, self._expected):
                await PlainTextResponse(UNAUTHORIZED, 401)(scope, receive, send)
                return
        await self._app(scope, receive, send)


def http_app(server: MCPServer, token: str) -> ASGIApp:
    """Return the MCP endpoint at ``/mcp`` behind the bearer gate."""
    return BearerGate(server.streamable_http_app(streamable_http_path=PATH, host=HOST), token)


def run_http(server: MCPServer, port: int, token: str) -> None:
    """Serve MCP on ``127.0.0.1:port`` until stopped; no access log."""
    uvicorn.run(
        http_app(server, token), host=HOST, port=port, log_level="warning", access_log=False
    )
