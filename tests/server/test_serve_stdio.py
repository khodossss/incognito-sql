"""A real `serve` process: its stderr carries no value, even when the database errs."""

import logging
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters
from mcp.types import TextContent

from incognito_sql.core.pipeline import Gateway

from .conftest import CANARY, CHILD, World

# Passes the policy; SQLite fails at run time (integer overflow) with the canary bound.
DB_ERROR_SQL = (
    "SELECT abs(-9223372036854775807 - 1) FROM people WHERE full_name = 'Zqcanary Person'"
)


def test_the_probe_would_leak_at_debug(gateway: Gateway, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="incognito_sql"):
        assert gateway.query(DB_ERROR_SQL, "c1") == {"error": "db_error", "sqlstate": None}
    assert CANARY in caplog.text.casefold()  # so the stderr check below has teeth


def test_serve_stderr_has_no_canary_after_a_db_error(world: World, tmp_path: Path) -> None:
    err = tmp_path / "stderr.txt"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", CHILD, str(err), "serve", "--config", str(world.config)],
        env=dict(os.environ),
    )
    replies: list[str] = []

    async def run() -> None:
        async with Client(params) as client:
            for sql in (DB_ERROR_SQL, "SELECT full_name FROM people"):
                [content] = (await client.call_tool("query", {"sql": sql})).content
                assert isinstance(content, TextContent)
                replies.append(content.text)

    anyio.run(run)
    assert '"db_error"' in replies[0]
    assert "/v/tk_" in replies[1]
    assert CANARY not in "".join(replies).casefold()
    assert CANARY not in err.read_text(encoding="utf-8", errors="replace").casefold()
