"""A tool's answer as the adapter reads it: results, JSON-RPC errors, a server gone."""

import pytest
from mcp import MCPError
from mcp.types import INTERNAL_ERROR, REQUEST_TIMEOUT, CallToolResult, TextContent

from bench.adapters.base import ANSWERED, REFUSED
from bench.adapters.calls import answer, read


def _rows(text: str, is_error: bool) -> tuple[str, list[list[object]] | None]:  # noqa: FBT001
    return (REFUSED if is_error else ANSWERED), [[text]]


def _fail(code: int) -> CallToolResult:
    raise MCPError(code, "query execution failed: no such column: nope")


def test_a_json_rpc_error_is_a_refusal_with_its_text() -> None:
    got = answer(lambda: _fail(INTERNAL_ERROR))
    assert read(got, _rows) == (
        REFUSED,
        f"MCPError {INTERNAL_ERROR}: query execution failed: no such column: nope",
        None,
    )


def test_the_error_data_is_read_too() -> None:
    def fail() -> CallToolResult:
        raise MCPError(-32601, "blocked by sqlGuard", {"tool": "x"})

    status, text, _ = read(answer(fail), _rows)
    assert status == REFUSED
    assert "blocked by sqlGuard" in text
    assert '"tool": "x"' in text


def test_a_timeout_is_no_answer() -> None:
    with pytest.raises(MCPError):
        answer(lambda: _fail(REQUEST_TIMEOUT))


def test_a_result_and_its_structured_content_are_read() -> None:
    result = CallToolResult(
        content=[TextContent(type="text", text="x")], structured_content={"k": 1}
    )
    assert read(answer(lambda: result), _rows) == (ANSWERED, 'x\n{"k": 1}', [["x"]])
