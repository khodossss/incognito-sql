"""A real `serve` process that also serves cards: stdout stays MCP, stderr stays clean."""

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import IO

import httpx2

from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.web.session import Sessions

from .conftest import CANARY, CHILD, KEY, TOKEN, World

TIMEOUT_S = 30


class _Peer:
    """Speaks newline-delimited JSON-RPC to the child and keeps every stdout line."""

    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdin is not None
        assert proc.stdout is not None
        self._proc = proc
        self._stdin: IO[bytes] = proc.stdin
        self.lines: list[bytes] = []
        self._stdout: IO[bytes] = proc.stdout
        self._inbox: queue.Queue[bytes] = queue.Queue()
        self._reader = threading.Thread(target=self._read, args=(proc.stdout,), daemon=True)
        self._reader.start()

    def _read(self, out: IO[bytes]) -> None:
        for line in out:
            self.lines.append(line)
            self._inbox.put(line)

    def send(self, message: dict[str, object]) -> None:
        self._stdin.write(json.dumps(message).encode() + b"\n")
        self._stdin.flush()

    def call(self, ident: int, method: str, params: dict[str, object]) -> dict[str, object]:
        self.send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        while True:
            reply = json.loads(self._inbox.get(timeout=TIMEOUT_S))
            if reply.get("id") == ident:
                return dict(reply["result"])

    def finish(self) -> None:
        self._stdin.close()
        self._proc.wait(timeout=TIMEOUT_S)
        self._reader.join(TIMEOUT_S)
        self._stdout.close()


def _start(world: World, err: Path) -> _Peer:
    proc = subprocess.Popen(  # noqa: S603 -- this interpreter, the real entry point
        [sys.executable, "-c", CHILD, str(err), "serve", "--config", str(world.config)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=dict(os.environ),
    )
    peer = _Peer(proc)
    hello = {"name": "test", "version": "0"}
    peer.call(
        1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": hello}
    )
    peer.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return peer


def _cards(world: World, port: int, token: str) -> list[str]:
    sessions = Sessions(world.config.parent / "field.tokens.db", Cipher(KEY))
    try:
        code = sessions.issue_code()
    finally:
        sessions.close()
    with httpx2.Client(base_url=f"http://127.0.0.1:{port}", timeout=TIMEOUT_S) as http:
        login = http.get(f"/login/{code}")
        assert login.status_code == 303
        cookie = {"cookie": login.headers["set-cookie"].split(";", 1)[0]}
        pages = [http.get(path, headers=cookie) for path in (f"/v/{token}", "/p/people/3")]
        assert http.get(f"/v/{token}", headers={"host": "evil.test"}).status_code == 400
    assert [p.status_code for p in pages] == [200, 200]
    return [p.text for p in pages]


def test_cards_beside_stdio_keep_both_streams_clean(
    world: World, free_port: int, tmp_path: Path
) -> None:
    world.write_config(f"web_port: {free_port}\n")
    err = tmp_path / "stderr.txt"
    peer = _start(world, err)
    try:
        sql = {"sql": "SELECT full_name FROM people WHERE id = 3"}
        answer = peer.call(2, "tools/call", {"name": "query", "arguments": sql})
        match = TOKEN.search(json.dumps(answer))
        assert match is not None
        pages = _cards(world, free_port, match.group())
    finally:
        peer.finish()
    assert all(CANARY in page.casefold() for page in pages)  # the cards did show the value
    assert peer.lines
    for line in peer.lines:
        assert json.loads(line)["jsonrpc"] == "2.0"
    assert CANARY not in b"".join(peer.lines).decode().casefold()
    assert CANARY not in err.read_text(encoding="utf-8", errors="replace").casefold()
