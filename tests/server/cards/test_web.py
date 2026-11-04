"""`incognito-sql web`, and the cards that `serve` starts when their port is free."""

import socket
import threading
from typing import TYPE_CHECKING

import httpx2
import pytest

from incognito_sql import cli
from incognito_sql.web.run import THREAD_NAME

from .conftest import Browser, Runs, World, run_cli

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


def test_web_serves_in_the_foreground(world: World, free_port: int, runs: Runs) -> None:
    assert run_cli(world, "web", f"web_port: {free_port}\n") == 0
    assert [address for _, address in runs.calls] == [("127.0.0.1", free_port)]


def test_web_on_a_busy_port_is_one_line(
    world: World,
    free_port: int,
    held: socket.socket,
    runs: Runs,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert held.fileno() != -1
    assert run_cli(world, "web", f"web_port: {free_port}\n") == 1
    assert capsys.readouterr().err == f"incognito-sql: port {free_port} on 127.0.0.1 is busy\n"
    assert runs.calls == []


@pytest.mark.parametrize("command", ["web", "login"])
def test_web_and_login_need_the_web_enabled(
    world: World, runs: Runs, browser: Browser, command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_cli(world, command, "web_enabled: false\n") == 2
    assert capsys.readouterr().err == "incognito-sql: the web is disabled in the config\n"
    assert (runs.calls, browser.urls) == ([], [])


def _web_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == THREAD_NAME]


def test_serve_runs_the_cards_beside_stdio(
    world: World, free_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers: list[int] = []

    def stdio(_server: "MCPServer") -> None:
        host = {"host": f"127.0.0.1:{free_port}"}
        answers.append(httpx2.get(f"http://127.0.0.1:{free_port}/", headers=host).status_code)

    monkeypatch.setattr(cli, "_run_stdio", stdio)
    assert run_cli(world, "serve", f"web_port: {free_port}\n") == 0
    assert answers == [401]
    assert _web_threads() == []


@pytest.mark.parametrize("extra", ["web_enabled: false\n", ""])
def test_serve_without_a_free_port_or_web_has_no_cards(
    world: World, held: socket.socket, monkeypatch: pytest.MonkeyPatch, extra: str
) -> None:
    port = int(held.getsockname()[1])
    threads: list[list[threading.Thread]] = []
    monkeypatch.setattr(cli, "_run_stdio", lambda _server: threads.append(_web_threads()))
    assert run_cli(world, "serve", f"web_port: {port}\n{extra}") == 0
    assert threads == [[]]
