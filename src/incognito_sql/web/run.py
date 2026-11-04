"""Running the card web: its parts, its one listener on 127.0.0.1, its server thread."""

import logging
import socket
import sys
import threading
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from starlette.applications import Starlette

from incognito_sql.core.budget import LiteralBudget
from incognito_sql.core.config import Declaration
from incognito_sql.core.db import make_engine
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.store import TokenStore
from incognito_sql.web.app import build_app
from incognito_sql.web.session import Sessions

HOST = "127.0.0.1"
THREAD_NAME = "incognito-sql-web"
_STOP_WAIT_S = 10
_LOG = logging.getLogger("incognito_sql.web")


@dataclass
class WebParts:
    """The card app and what it holds open."""

    app: Starlette
    sessions: Sessions
    opened: ExitStack

    def close(self) -> None:
        """Close the stores and the database engine."""
        self.opened.close()


def open_web(
    decl: Declaration, dsn: str, store_path: Path, domain: str, cipher: Cipher
) -> WebParts:
    """Open the stores and a read-only engine of their own, and build the app on them."""
    with ExitStack() as opened:
        engine = make_engine(
            dsn, decl.dialect, statement_timeout_ms=decl.limits.statement_timeout_ms
        )
        opened.callback(engine.dispose)
        store = TokenStore(store_path, cipher, domain, decl.token_ttl_s)
        opened.callback(store.close)
        sessions = Sessions(store_path, cipher, session_ttl_s=decl.session_ttl_s)
        opened.callback(sessions.close)
        budget = LiteralBudget(store_path, cipher, decl.limits)
        opened.callback(budget.close)
        app = build_app(decl, store, engine, sessions, budget)
        return WebParts(app, sessions, opened.pop_all())


def bind_local(port: int) -> socket.socket | None:
    """Listen on 127.0.0.1:port, or return None if anything already holds the port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32":  # otherwise Windows lets a second listener share the port
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((HOST, port))
        sock.listen()
    except OSError:
        sock.close()
        return None
    return sock


class LocalWeb:
    """Serves the parts on a bound socket; closes both when the server ends."""

    def __init__(self, parts: WebParts, sock: socket.socket) -> None:
        """Prepare a quiet server: no access log, nothing on stdout."""
        config = uvicorn.Config(
            parts.app,
            log_config=None,
            log_level="warning",
            access_log=False,
            lifespan="off",
            server_header=False,
        )
        self._server = uvicorn.Server(config)
        self._parts = parts
        self._sock = sock
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        """True while the background thread lives."""
        return self._thread is not None and self._thread.is_alive()

    def run(self) -> bool:
        """Serve until stopped or interrupted; False if the server failed."""
        try:
            self._server.run(sockets=[self._sock])
        except KeyboardInterrupt:  # Ctrl+C in the foreground is a normal stop
            return True
        except Exception as exc:  # noqa: BLE001 -- a traceback may quote request data
            _LOG.warning("web stopped: %s", type(exc).__name__)
            return False
        finally:
            self._sock.close()
            self._parts.close()
        return True

    def start(self) -> None:
        """Serve in a daemon thread."""
        self._thread = threading.Thread(target=self.run, name=THREAD_NAME, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Ask the server to finish and wait for its thread."""
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(_STOP_WAIT_S)
