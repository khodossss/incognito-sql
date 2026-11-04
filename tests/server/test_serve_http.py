"""MCP over HTTP on 127.0.0.1: nothing without the bearer token, the same tools with it."""

import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import anyio
import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent
from starlette.testclient import TestClient

from incognito_sql.core.budget import SESSIONLESS
from incognito_sql.core.pipeline import Gateway
from incognito_sql.mcp.http import http_app
from incognito_sql.mcp.server import build_server
from incognito_sql.mcp.token import TOKEN_ENV, TokenError, service_token

from .conftest import CANARY, TOKEN, GatewayFactory

SECRET = "s" * 40


def test_the_token_comes_from_the_environment() -> None:
    assert service_token({TOKEN_ENV: SECRET}) == SECRET


@pytest.mark.parametrize("env", [{}, {TOKEN_ENV: ""}, {TOKEN_ENV: "short-token"}])
def test_a_missing_or_short_token_stops_the_start(env: dict[str, str]) -> None:
    with pytest.raises(TokenError) as caught:
        service_token(env)
    assert TOKEN_ENV in str(caught.value)
    assert "short-token" not in str(caught.value)


@pytest.mark.parametrize(
    "headers",
    [{}, {"authorization": f"Bearer {SECRET}x"}, {"authorization": SECRET}, {"x-token": SECRET}],
)
def test_requests_without_the_token_get_401(gateway: Gateway, headers: dict[str, str]) -> None:
    app = http_app(build_server(gateway, "http"), SECRET)
    with TestClient(app, base_url="http://127.0.0.1:8766") as client:
        response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1})
    assert response.status_code == 401
    assert response.text == "unauthorized\n"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _serving(gateway: Gateway) -> Iterator[str]:
    port = _free_port()
    config = uvicorn.Config(
        http_app(build_server(gateway, SESSIONLESS), SECRET),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(10)


@pytest.fixture
def served(gateway: Gateway) -> Iterator[str]:
    with _serving(gateway) as url:
        yield url


def test_a_client_with_the_token_queries_over_http(
    served: str, gateway: Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    replies: list[dict[str, object]] = []
    connections: list[str] = []
    query = gateway.query

    def counted(sql: str, connection: str) -> dict[str, object]:
        connections.append(connection)
        return query(sql, connection)

    monkeypatch.setattr(gateway, "query", counted)

    async def ask(client: Client) -> None:
        tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == {"query", "describe"}
        result = await client.call_tool(
            "query", {"sql": "SELECT full_name FROM people WHERE full_name = 'Ivan Petrov'"}
        )
        [content] = result.content
        assert isinstance(content, TextContent)
        replies.append(json.loads(content.text))

    async def run() -> None:
        headers = {"Authorization": f"Bearer {SECRET}"}
        async with (  # two sessions open at once
            httpx2.AsyncClient(headers=headers) as http,
            Client(streamable_http_client(served, http_client=http)) as first,
            Client(streamable_http_client(served, http_client=http)) as second,
        ):
            await ask(first)
            await ask(first)
            await ask(second)

    anyio.run(run)
    for found in replies:
        rows = found["rows"]
        assert isinstance(rows, list)
        assert TOKEN.search(rows[0][0])
    assert CANARY not in json.dumps(replies).casefold()
    # HTTP requests carry no session: the service counts by the installation window.
    assert connections == [SESSIONLESS] * 3


T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
BY_NAME = "SELECT id FROM people WHERE full_name = '{}'"


def test_the_service_budget_refills_with_the_window_for_every_client(
    make_gateway: GatewayFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = make_gateway("limits: {literal_budget: 1, literal_window_s: 60}\n")
    clock = [T0]
    query = gateway.query
    monkeypatch.setattr(gateway, "query", lambda sql, conn: query(sql, conn, clock[0]))
    errors: list[object] = []

    async def ask(client: Client, name: str) -> None:
        result = await client.call_tool("query", {"sql": BY_NAME.format(name)})
        [content] = result.content
        assert isinstance(content, TextContent)
        errors.append(json.loads(content.text).get("error"))

    async def run(url: str) -> None:
        headers = {"Authorization": f"Bearer {SECRET}"}
        async with (
            httpx2.AsyncClient(headers=headers) as http,
            Client(streamable_http_client(url, http_client=http)) as first,
            Client(streamable_http_client(url, http_client=http)) as second,
        ):
            await ask(first, "Zqno A")
            await ask(second, "Zqno B")  # a burst across clients: the window holds it
            clock[0] = T0 + timedelta(seconds=120)
            await ask(first, "Zqno C")  # the window has passed: a fresh literal answers
            await ask(second, "Zqno C")  # the same literal costs nothing more

    with _serving(gateway) as url:
        anyio.run(run, url)
    assert errors == [None, "literal_budget", None, None]
