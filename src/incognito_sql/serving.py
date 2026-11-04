"""Running the MCP server: over stdio for the client that starts it, or as a service over HTTP."""

import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from incognito_sql.core.config import Declaration
from incognito_sql.core.config.report import protection_warnings
from incognito_sql.web.run import HOST, LocalWeb, bind_local
from incognito_sql.wiring import open_cards, open_gateway

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer  # noqa: TID251 -- typing only, never at runtime

EXIT_FAILED = 1
EXIT_USAGE = 2


class StartError(Exception):
    """The server could not start; the message is one safe line (never the DSN)."""

    def __init__(self, message: str, code: int = EXIT_FAILED) -> None:
        """Hold the message and the exit code."""
        super().__init__(message)
        self.code = code


def opened[T](open_parts: Callable[[], T], sock: socket.socket | None = None) -> T:
    """Open parts that touch the database; any failure is one safe line."""
    try:
        return open_parts()
    except Exception as exc:  # noqa: BLE001 -- any driver or file error stops the start
        if sock is not None:
            sock.close()
        # Driver messages may quote the DSN: only the exception type is shown.
        msg = f"cannot open the database ({type(exc).__name__})"
        raise StartError(msg) from None


def cards_socket(decl: Declaration, *, required: bool) -> socket.socket | None:
    """Bind the cards port; None means something already listens there (fine unless required)."""
    if not decl.web_enabled:
        msg = "the web is disabled in the config"
        raise StartError(msg, EXIT_USAGE)
    sock = bind_local(decl.web_port)
    if sock is None and required:
        msg = f"port {decl.web_port} on {HOST} is busy"
        raise StartError(msg)
    return sock


def serve(  # noqa: PLR0913, PLR0917
    config: Path,
    decl: Declaration,
    dsn: str,
    key: bytes,
    run: Callable[["MCPServer"], None],
    connection_id: str,
    *,
    cards_required: bool = False,
) -> int:
    """Open the gateway and the cards, run the server, close all.

    ``connection_id`` names the literal budget: one id per stdio process; the service
    passes SESSIONLESS, since an HTTP client can start afresh with every request.
    With ``cards_required`` (the service) a busy cards port stops the start: whoever
    holds it would receive the human's sign-in links. Otherwise a busy port means
    another process serves the cards: no web here, no error. A protection profile
    that admits more than the base set is named on stderr once the gateway is open.
    An open view, or an open partition, child or parent table without every row rule
    of its family, stops it.
    """
    gateway = opened(lambda: open_gateway(config, decl, dsn, key))
    readers = gateway.unruled_readers()
    if readers:
        gateway.close()
        msg = (
            f"{', '.join(readers)}: open, a view or without every row rule of its "
            "partitions, child and parent tables, and may show rows of a table with row "
            "rules unmasked; give a table the rules, or list it under verified_relations "
            "once you have checked it shows no ruled row"
        )
        raise StartError(msg, EXIT_USAGE)
    for line in protection_warnings(decl):
        sys.stderr.write(f"incognito-sql: {line}\n")
    web: LocalWeb | None = None
    try:
        # The MCP SDK is the optional extra `[mcp]`: only the servers need it.
        from incognito_sql.mcp.server import build_server  # noqa: PLC0415

        sock = cards_socket(decl, required=cards_required) if decl.web_enabled else None
        if sock is not None:
            web = LocalWeb(opened(lambda: open_cards(config, decl, dsn, key), sock), sock)
            web.start()
        run(build_server(gateway, connection_id))
    finally:
        if web is not None:
            web.stop()
        gateway.close()
    return 0


def http_run(port: int, token: str) -> Callable[["MCPServer"], None]:
    """Return a runner that serves MCP over HTTP on ``127.0.0.1:port`` behind the token."""

    def run(server: "MCPServer") -> None:
        from incognito_sql.mcp.http import run_http  # noqa: PLC0415 -- needs the [mcp] extra

        run_http(server, port, token)

    return run
