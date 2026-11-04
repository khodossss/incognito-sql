"""Fakes for the card commands: the foreground server, the browser, a held port."""

import socket
import webbrowser
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import pytest
import uvicorn
from starlette.applications import Starlette

from incognito_sql import cli
from incognito_sql.web.run import bind_local

from ..conftest import KEY, World  # noqa: TID252 -- the shared end-to-end world

__all__ = ["KEY", "Address", "Browser", "Runs", "World", "login_code", "run_cli"]

Address = tuple[str, int]


@dataclass
class Runs:
    """Foreground server runs, faked: which app was served on which address."""

    calls: list[tuple[Starlette, Address]] = field(default_factory=list)
    during: Callable[[Starlette, Address], None] | None = None


@dataclass
class Browser:
    """URLs sent to the browser, and whether it pretends to open them."""

    urls: list[str] = field(default_factory=list)
    works: bool = True


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> Runs:
    record = Runs()

    def fake(self: uvicorn.Server, sockets: list[socket.socket] | None = None) -> None:
        assert sockets is not None
        app, address = self.config.app, sockets[0].getsockname()
        assert isinstance(app, Starlette)
        record.calls.append((app, address))
        if record.during:
            record.during(app, address)

    monkeypatch.setattr(uvicorn.Server, "run", fake)
    return record


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> Browser:
    record = Browser()

    def fake_open(url: str) -> bool:
        record.urls.append(url)
        return record.works

    monkeypatch.setattr(webbrowser, "open", fake_open)
    return record


@pytest.fixture
def held(free_port: int) -> Iterator[socket.socket]:
    """The cards port, held as if another process served it."""
    sock = bind_local(free_port)
    assert sock is not None
    yield sock
    sock.close()


def run_cli(world: World, command: str, extra: str = "") -> int:
    world.write_config(extra)
    return cli.main([command, "--config", str(world.config)])


def login_code(url: str, port: int) -> str:
    prefix = f"http://127.0.0.1:{port}/login/"
    assert url.startswith(prefix)
    return url.removeprefix(prefix)
