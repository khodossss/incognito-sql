"""`incognito-sql login`: a one-time link in the browser, and the cards if none serve them."""

import socket

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from incognito_sql import cli
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.web.run import bind_local
from incognito_sql.web.session import Sessions

from .conftest import KEY, Address, Browser, Runs, World, login_code, run_cli


def test_with_a_web_running_it_only_opens_the_link(
    world: World, free_port: int, held: socket.socket, browser: Browser, runs: Runs
) -> None:
    assert held.fileno() != -1
    assert run_cli(world, "login", f"web_port: {free_port}\n") == 0
    [url] = browser.urls
    assert runs.calls == []
    other = Sessions(world.config.parent / "field.tokens.db", Cipher(KEY))
    try:  # the running web is another process: it shares the token store file
        assert other.valid(other.exchange(login_code(url, free_port)))
    finally:
        other.close()


def test_without_a_web_it_serves_the_cards_itself(
    world: World, free_port: int, browser: Browser, runs: Runs
) -> None:
    statuses: list[int] = []

    def during(app: Starlette, address: Address) -> None:
        assert address == ("127.0.0.1", free_port)
        [url] = browser.urls  # the browser is sent before the server runs
        base = f"http://127.0.0.1:{free_port}"
        with TestClient(app, base_url=base, follow_redirects=False) as client:
            statuses.append(client.get(f"/login/{login_code(url, free_port)}").status_code)

    runs.during = during
    assert run_cli(world, "login", f"web_port: {free_port}\n") == 0
    assert statuses == [303]
    freed = bind_local(free_port)
    assert freed is not None
    freed.close()


def test_without_a_browser_the_link_is_printed(
    world: World,
    free_port: int,
    held: socket.socket,
    browser: Browser,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert held.fileno() != -1
    browser.works = False
    assert run_cli(world, "login", f"web_port: {free_port}\n") == 0
    [url] = browser.urls
    assert capsys.readouterr().err == f"incognito-sql: open {url}\n"


def test_print_writes_the_link_to_stdout_without_a_browser(
    world: World,
    free_port: int,
    held: socket.socket,
    browser: Browser,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert held.fileno() != -1
    world.write_config(f"web_port: {free_port}\n")
    assert cli.main(["login", "--config", str(world.config), "--print"]) == 0
    assert browser.urls == []
    url = capsys.readouterr().out.strip()
    other = Sessions(world.config.parent / "field.tokens.db", Cipher(KEY))
    try:
        assert other.valid(other.exchange(login_code(url, free_port)))
    finally:
        other.close()
