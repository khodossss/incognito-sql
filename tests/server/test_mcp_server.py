"""The MCP surface through the SDK's in-process client: two tools, JSON text, no values."""

import json
from typing import Any

import anyio
from mcp import Client
from mcp.types import TextContent

from incognito_sql.core.pipeline import Gateway
from incognito_sql.mcp.server import build_server

from .conftest import CANARY, TOKEN


def _talk(gateway: Gateway, calls: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    async def run() -> None:
        async with Client(build_server(gateway, "conn-1")) as client:
            seen["instructions"] = client.instructions or ""
            seen["tools"] = (await client.list_tools()).tools
            replies = []
            for name, args in calls:
                result = await client.call_tool(name, args)
                [content] = result.content
                assert isinstance(content, TextContent)
                assert result.is_error is False
                replies.append(json.loads(content.text))
            seen["replies"] = replies

    anyio.run(run)
    return seen


def test_a_refusal_tells_the_agent_what_to_do(gateway: Gateway) -> None:
    [reply] = _talk(gateway, [("query", {"sql": "SELECT 1; SELECT 2"})])["replies"]
    assert reply["error"] == "multiple_statements"
    assert reply["retry"] == "rewrite"
    assert reply["hint"] == "Send one statement per call."


def test_exactly_query_and_describe(gateway: Gateway) -> None:
    seen = _talk(gateway, [])
    assert {t.name for t in seen["tools"]} == {"query", "describe"}
    query = next(t for t in seen["tools"] if t.name == "query")
    assert set(query.input_schema["properties"]) == {"sql"}
    assert query.annotations.read_only_hint is True


def test_descriptions_explain_pseudonyms_without_values(gateway: Gateway) -> None:
    seen = _talk(gateway, [])
    text = seen["instructions"] + "".join(t.description or "" for t in seen["tools"])
    lowered = text.casefold()
    for phrase in ("pseudonym", "not missing", "tk_", "hidden", "same link"):
        assert phrase in lowered, phrase
    assert CANARY not in lowered
    assert "8765" not in text  # the port is the configured one, not a constant
    assert "reveal" not in {t.name for t in seen["tools"]}


def test_instructions_link_rows_to_person_cards_in_any_language(gateway: Gateway) -> None:
    seen = _talk(gateway, [])
    text = seen["instructions"] + "".join(t.description or "" for t in seen["tools"])
    assert "person_key" in text
    assert "/p/<table>/" in text
    assert "language the user writes in" in text
    # No ready-made label in another language: it would leak into an English chat.
    assert all(c.isascii() for c in text if c.isalpha())


def test_tools_answer_with_json(gateway: Gateway) -> None:
    seen = _talk(
        gateway,
        [
            ("describe", {}),
            ("query", {"sql": "SELECT full_name FROM people WHERE full_name = 'Ivan Petrov'"}),
            ("query", {"sql": "SELECT secret_note FROM people"}),
        ],
    )
    view, found, refused = seen["replies"]
    assert set(view["tables"]) == {"people", "orders", "cards", "staff"}
    assert view["dbms"] == "SQLite"
    assert TOKEN.search(found["rows"][0][0])
    assert refused["error"] == "hidden_column"
    assert refused["sqlstate"] is None
    assert refused["retry"] == "rewrite"
    assert CANARY not in json.dumps(seen["replies"]).casefold()
