"""Drive a competitor as an MCP stdio server through the MCP SDK client.

The server is its own process (here, a docker container). Its stderr and an
audit file it writes are drained after each query. A query that times out or breaks the
transport is an ``error`` and restarts the server, so the cases after it still run; a
JSON-RPC error the server sends back is its refusal.
"""

import contextlib
import json
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from typing import Any

from anyio.from_thread import start_blocking_portal
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

from bench.adapters.base import (
    ERROR,
    FOREIGN_TOKENS,
    Info,
    NotRunError,
    Outcome,
    Rows,
    Tail,
    timed,
)
from bench.adapters.calls import Arguments, Parse, answer, read, unusable

RESTARTS = 10  # after this many restarts the server counts as gone
START_S, QUERY_S = 180.0, 30.0  # a first start may pull or build its image


class StdioAdapter:
    """A tool reached over MCP stdio; ``arguments`` maps one SQL query to the tool's input."""

    mode: str | None = None
    tokens: Mapping[str, str] = FOREIGN_TOKENS

    def __init__(  # noqa: PLR0913 -- one tool, one launch, one mapping, its files
        self,
        info: Info,
        dialect: str,
        params: StdioServerParameters,
        calls: tuple[Arguments, Parse],
        *,
        workdir: Path,
        audit: Path | None = None,
        start_s: float = START_S,
    ) -> None:
        """Start the server, list its tools, and check the query tool's input."""
        self.info, self.dialect, self._params = info, dialect, params
        self._start_s = start_s
        self._arguments, self._parse = calls
        self.restarts, self._live = 0, False
        workdir.mkdir(parents=True, exist_ok=True)
        self._stderr = Tail(workdir / "stderr.txt")
        self._audit = Tail(audit) if audit else None
        self._err = self._stderr.path.open("w", encoding="utf-8")
        try:
            tools = self._connect()
        except NotRunError:
            self._err.close()
            raise
        self._listing = json.dumps(
            {"instructions": self._client.instructions, "tools": list(tools.values())}
        )
        problem = unusable(tools.get(info.tool), set(self._arguments("")))
        if problem:
            self.close()
            msg = f"tool {info.tool!r} {problem}"
            raise NotRunError(msg)

    def _connect(self) -> dict[str, dict[str, Any]]:
        self._portal_cm = start_blocking_portal()
        self._portal = self._portal_cm.__enter__()
        transport = stdio_client(self._params, errlog=self._err)
        client = Client(transport, mode="legacy", read_timeout_seconds=self._start_s)
        self._client_cm = self._portal.wrap_async_context_manager(client)
        try:
            self._client = self._client_cm.__enter__()
        except Exception as exc:
            self._portal_cm.__exit__(None, None, None)
            msg = f"the server did not start: {type(exc).__name__}"
            raise NotRunError(msg) from exc
        self._live = True
        try:
            listed = self._portal.call(partial(self._client.list_tools)).tools
        except Exception as exc:
            self._disconnect()
            msg = f"the server lists no tools: {type(exc).__name__}"
            raise NotRunError(msg) from exc
        return {t.name: t.model_dump(mode="json") for t in listed}

    def query(self, sql: str) -> Outcome:
        """Call the tool with ``sql``; a failed call is an ``error`` and restarts the server."""
        if self.restarts > RESTARTS:
            return Outcome(ERROR, "the server stopped answering", 0.0)

        def call() -> tuple[str, str, Rows | None]:
            send = partial(self._portal.call, self._send, self._arguments(sql))
            return read(answer(send), self._parse)

        outcome = timed(call)
        if outcome.status == ERROR:
            self._restart()
        return outcome

    async def _send(self, args: dict[str, object]) -> CallToolResult:
        return await self._client.call_tool(self.info.tool, args, QUERY_S)

    def _restart(self) -> None:
        self.restarts += 1
        try:
            self._disconnect()
            self._connect()
        except Exception:  # noqa: BLE001 -- a server that cannot come back is gone
            self.restarts = RESTARTS + 1

    def channels(self) -> dict[str, str]:
        """Return new stderr and new audit lines."""
        out = {"stderr": self._stderr.read()}
        if self._audit is not None:
            out["audit"] = self._audit.read()
        return out

    def static(self) -> str:
        """Return the server's instructions and tool listing as JSON."""
        return self._listing

    def close(self) -> None:
        """End the session; the server process exits with it."""
        try:
            self._disconnect()
        finally:
            self._err.close()

    def _disconnect(self) -> None:
        if not self._live:
            return  # never connected, or already let go after a failed restart
        self._live = False
        try:
            with contextlib.suppress(Exception):  # a dead server cannot end its session
                self._client_cm.__exit__(None, None, None)
        finally:
            self._portal_cm.__exit__(None, None, None)
