"""How a query reaches a competitor's tool and how its answer is read."""

import json
from collections.abc import Callable
from typing import Any

from mcp import MCPError
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT, CallToolResult

from bench.adapters.base import ANSWERED, REFUSED, Rows

Parse = Callable[[str, bool], tuple[str, Rows | None]]
Arguments = Callable[[str], dict[str, object]]
_GONE = (CONNECTION_CLOSED, REQUEST_TIMEOUT)  # no answer: the server is restarted


def answer(call: Callable[[], CallToolResult]) -> CallToolResult | str:
    """Run ``call``; a JSON-RPC error the server sent back is its answer, given as text."""
    try:
        return call()
    except MCPError as exc:
        if exc.code in _GONE:
            raise
        text = f"MCPError {exc.code}: {exc.message}"  # data too: it may carry a value
        return text if exc.data is None else f"{text}\n{json.dumps(exc.data, default=str)}"


def read(result: CallToolResult | str, parse: Parse) -> tuple[str, str, Rows | None]:
    """Return the status, the text the model reads and the rows of a tool's answer.

    A JSON-RPC error is a refusal; structured content is part of the text, since a
    client may show it.
    """
    if isinstance(result, str):
        return REFUSED, result, None
    content = "\n".join(getattr(c, "text", "") for c in result.content)
    status, rows = parsed(parse, content, bool(result.is_error))
    extra = result.structured_content
    text = content if extra is None else f"{content}\n{json.dumps(extra)}"
    return status, text, rows


def parsed(parse: Parse, text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001
    """Parse an answer; text the parser cannot read keeps its status and has no rows."""
    try:
        return parse(text, is_error)
    except (ValueError, AttributeError, TypeError):
        return (REFUSED if is_error else ANSWERED), None


def unusable(tool: dict[str, Any] | None, given: set[str]) -> str:
    """Say why the query tool cannot be called with ``given`` arguments; empty if it can."""
    if tool is None:
        return "not listed by the server"
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    missing = {str(k) for k in schema.get("required") or []} - given
    return f"requires {sorted(missing)}" if missing else ""
