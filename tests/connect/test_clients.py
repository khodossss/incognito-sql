"""Each client's entry names variables, never values, and pins the release it fetches."""

import base64
import json
import secrets
import shlex
import tomllib
from pathlib import Path

import pytest

from incognito_sql.connect.clients import (
    CLIENTS,
    block,
    http,
    stdio,
    valid_variable,
)

URL = "http://127.0.0.1:8766/mcp"


@pytest.mark.parametrize(
    ("dialect", "extras"),
    [
        ("sqlite", "mcp"),
        ("duckdb", "mcp,duckdb"),
        ("postgres", "mcp,postgres"),
        ("tsql", "mcp,mssql"),
    ],
)
def test_a_release_is_pinned_with_its_driver(dialect: str, extras: str) -> None:
    server = stdio("shop", Path("shop.yaml"), "SHOP_DSN", dialect, release="0.4.0", python="py")
    assert server.command[:3] == ("uvx", "--from", f"incognito-sql[{extras}]==0.4.0")
    assert server.command[-2] == "--config"
    assert Path(server.command[-1]).is_absolute()


def test_without_a_release_the_entry_runs_this_installation() -> None:
    server = stdio(
        "shop", Path("shop.yaml"), "SHOP_DSN", "sqlite", release=None, python="/venv/bin/python"
    )
    assert server.command[:4] == ("/venv/bin/python", "-m", "incognito_sql", "serve")


def test_no_random_token_passes_for_a_variable() -> None:
    for _ in range(400):
        tokens = (
            secrets.token_hex(32),
            secrets.token_hex(32).upper(),
            secrets.token_urlsafe(32),
            "ghp_" + secrets.token_urlsafe(27),
            base64.b32encode(secrets.token_bytes(20)).decode().rstrip("="),
        )
        assert not any(map(valid_variable, tokens)), tokens
    for name in ("INCOGNITO_SQL_MCP_TOKEN", "SHOP_MCP_TOKEN", "TOKEN"):
        assert valid_variable(name), name


@pytest.mark.parametrize("client", CLIENTS)
def test_entries_name_variables(client: str) -> None:
    local = block(
        client,
        stdio("shop", Path("shop.yaml"), "SHOP_DSN", "postgres", release="0.4.0", python="py"),
    )
    remote = block(client, http("shop", URL, "SHOP_MCP_TOKEN"))
    assert "SHOP_DSN" in local
    assert "SHOP_MCP_TOKEN" in remote
    assert URL in remote


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("SHOP_DSN", True),
        ("DB", True),
        ("_x1", False),  # lower case: a token's alphabet
        ("d0123456789abcdef0123456789abcdef", False),
        ("postgresql://u:pw@h/db", False),
        ("1X", False),
        ("", False),
    ],
)
def test_a_variable_is_a_name_never_a_value(name: str, *, ok: bool) -> None:
    assert valid_variable(name) is ok


def test_claude_code_gets_a_command_with_the_name_before_its_variables() -> None:
    line = block(
        "claude-code",
        stdio("shop", Path("shop.yaml"), "SHOP_DSN", "sqlite", release="0.4.0", python="py"),
    )
    words = shlex.split(line)
    assert words[:6] == ["claude", "mcp", "add", "--scope", "project", "shop"]
    assert words[6:9] == ["-e", "SHOP_DSN=${SHOP_DSN}", "--"]
    remote = shlex.split(block("claude-code", http("shop", URL, "T")))
    assert remote[-2:] == ["-H", "Authorization: Bearer ${T}"]


def test_each_format_reads_back() -> None:
    server = stdio("shop", Path("shop.yaml"), "SHOP_DSN", "sqlite", release="0.4.0", python="py")
    codex = tomllib.loads(block("codex", server))["mcp_servers"]["shop"]
    assert codex["env_vars"] == ["SHOP_DSN", "INCOGNITO_SQL_KEY"]
    cursor = json.loads(block("cursor", server))["mcpServers"]["shop"]
    assert cursor["env"] == {"SHOP_DSN": "${env:SHOP_DSN}"}
    opencode = json.loads(block("opencode", http("shop", URL, "T")))["mcp"]["shop"]
    assert opencode == {
        "type": "remote",
        "url": URL,
        "headers": {"Authorization": "Bearer {env:T}"},
        "oauth": False,
    }
