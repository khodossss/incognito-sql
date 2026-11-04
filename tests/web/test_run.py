"""The local web process: one listener per port, a server that stops and closes its parts."""

import logging
import socket
import sqlite3
from pathlib import Path

import httpx2
import pytest
import uvicorn

from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.web.run import LocalWeb, WebParts, bind_local, open_web

from .conftest import DECL, PORT, Parts


def _open(parts: Parts, tmp_path: Path) -> WebParts:
    return open_web(
        DECL, f"sqlite:///{parts.db}", tmp_path / "web.tokens.db", "db:test", Cipher(bytes(32))
    )


def _port(sock: socket.socket) -> int:
    return int(sock.getsockname()[1])


def test_a_port_is_taken_once() -> None:
    first = bind_local(0)
    assert first is not None
    port = _port(first)
    assert first.getsockname()[0] == "127.0.0.1"
    assert bind_local(port) is None
    first.close()
    again = bind_local(port)
    assert again is not None
    again.close()


def test_the_web_serves_until_stopped(parts: Parts, tmp_path: Path) -> None:
    web_parts = _open(parts, tmp_path)
    sock = bind_local(0)
    assert sock is not None
    port = _port(sock)
    web = LocalWeb(web_parts, sock)
    web.start()
    try:
        answer = httpx2.get(f"http://127.0.0.1:{port}/", headers={"host": f"127.0.0.1:{PORT}"})
        assert answer.status_code == 401
    finally:
        web.stop()
    assert not web.running
    with pytest.raises(sqlite3.ProgrammingError):  # the parts are closed with the server
        web_parts.sessions.issue_code()
    freed = bind_local(port)
    assert freed is not None
    freed.close()


def test_a_failed_server_is_one_fixed_warning(
    parts: Parts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(_self: uvicorn.Server, sockets: list[socket.socket] | None = None) -> None:
        msg = f"Zzboom {sockets}"
        raise RuntimeError(msg)

    monkeypatch.setattr(uvicorn.Server, "run", broken)
    sock = bind_local(0)
    assert sock is not None
    with caplog.at_level(logging.WARNING):
        assert LocalWeb(_open(parts, tmp_path), sock).run() is False
    assert [r.getMessage() for r in caplog.records] == ["web stopped: RuntimeError"]
    assert sock.fileno() == -1  # closed
