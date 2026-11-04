"""The MCP stdio adapter against a stand-in server process: answers, errors, stderr."""

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from mcp import StdioServerParameters

from bench.adapters.base import ANSWERED, ERROR, REFUSED, Info, NotRunError, Rows
from bench.adapters.mcp_stdio import StdioAdapter

SERVER = Path(__file__).with_name("stdio_server.py")


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001
    return (REFUSED, None) if is_error else (ANSWERED, json.loads(text)["rows"])


def _open(tool: str, key: str, workdir: Path) -> StdioAdapter:
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    info = Info(name="stand-in", mechanism="echo", rung=1, tool=tool)
    calls = (lambda sql: {key: sql}, parse)
    return StdioAdapter(info, "sqlite", params, calls, workdir=workdir)


@pytest.fixture(scope="module")
def adapter(tmp_path_factory: pytest.TempPathFactory) -> Iterator[StdioAdapter]:
    opened = _open("echo", "sql", tmp_path_factory.mktemp("stdio"))
    yield opened
    opened.close()


def test_answer_rows_and_stderr(adapter: StdioAdapter) -> None:
    out = adapter.query("SELECT 1")
    assert (out.status, out.rows) == (ANSWERED, [["SELECT 1"]])
    assert out.ms > 0
    assert "log: SELECT 1" in adapter.channels()["stderr"]
    assert adapter.channels()["stderr"] == ""  # drained


def test_tool_error_is_a_refusal_with_its_text(adapter: StdioAdapter) -> None:
    out = adapter.query("bad query")
    assert out.status == REFUSED
    assert "Error executing tool echo" in out.text  # the server hides the message


def test_listing_names_the_tool(adapter: StdioAdapter) -> None:
    assert json.loads(adapter.static())["tools"][0]["name"] == "echo"


def test_missing_tool_or_argument_is_not_run(tmp_path: Path) -> None:
    with pytest.raises(NotRunError, match="not listed"):
        _open("nope", "sql", tmp_path / "a")
    with pytest.raises(NotRunError, match="requires"):
        _open("echo", "query", tmp_path / "b")


def test_a_hanging_query_is_an_error_and_the_server_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("bench.adapters.mcp_stdio.QUERY_S", 0.5)
    adapter = _open("echo", "sql", tmp_path)
    try:
        assert adapter.query("slow").status == ERROR
        assert adapter.restarts == 1
        assert adapter.query("SELECT 2").rows == [["SELECT 2"]]
        dead = StdioServerParameters(command=sys.executable, args=["-c", "raise SystemExit(3)"])
        adapter._params = dead  # noqa: SLF001 -- the next restart cannot succeed
        adapter._restart()  # noqa: SLF001 -- as after a failed query
        assert adapter.query("SELECT 3").text == "the server stopped answering"
    finally:
        adapter.close()  # also after a failed restart
