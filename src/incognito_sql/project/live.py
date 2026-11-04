"""The project's gateway and cards, opened on first use and again when the setup changes.

The client starts the server once per session, often before anything is set up. Each
call looks at the declaration and the DSN as they are now: a declaration written or
edited, or a DSN set, during the session is taken without a restart. What cannot open
is said in one safe line (never the DSN, never a driver's text).
"""

import hashlib
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from incognito_sql.connect.clients import valid_variable
from incognito_sql.core.config import Declaration, load_declaration
from incognito_sql.core.config.report import protection_warnings
from incognito_sql.core.pipeline import Gateway
from incognito_sql.problems import quiet_problem
from incognito_sql.project.dsn import Found
from incognito_sql.project.place import Place
from incognito_sql.serving import StartError, checked_gateway, opened
from incognito_sql.web.run import LocalWeb, WebParts, bind_local
from incognito_sql.wiring import open_cards


class NotReady(Exception):  # noqa: N818 -- a state the agent is told, not a failure
    """The setup is not complete; the message names what is missing and is safe to show."""


@dataclass(frozen=True)
class Setup:
    """What the project holds now: the declaration and where its DSN was found."""

    decl: Declaration | None
    problem: str | None
    found: Found | None


@dataclass
class _Open:
    stamp: tuple[int, str]
    decl: Declaration
    gateway: Gateway
    parts: WebParts | None
    web: LocalWeb | None


class Live:
    """The project's open parts, behind one lock."""

    def __init__(
        self,
        place: Place,
        find: Callable[[str, Path], Found | None],
        key: Callable[[], bytes],
    ) -> None:
        """Hold the project's place, how to find a DSN by name and how to load the key."""
        self._place, self._find, self._key = place, find, key
        self._lock = threading.Lock()
        self._open: _Open | None = None

    def setup(self) -> Setup:
        """Read the declaration and find its DSN, opening nothing."""
        config = self._place.config
        if not config.exists():
            return Setup(None, None, None)
        try:
            decl = load_declaration(config)
        except Exception as exc:  # noqa: BLE001 -- file, YAML or schema: any is a bad config
            return Setup(None, f"the declaration cannot be read: {quiet_problem(exc)}", None)
        if not valid_variable(decl.dsn_env):
            return Setup(decl, "the declaration's dsn_env must be a variable's NAME", None)
        return Setup(decl, None, self._find(decl.dsn_env, self._place.env_file))

    def find(self, name: str, env_file: Path) -> Found | None:
        """Find a DSN by its variable's name, as the setup does."""
        return self._find(name, env_file)

    def gateway(self) -> Gateway:
        """Return the gateway for the setup as it is now, reopened if it changed."""
        with self._lock:
            return self._current().gateway

    def cards(self) -> WebParts:
        """Return the cards this process serves; NotReady if another process holds the port."""
        with self._lock:
            opened_now = self._current()
            if opened_now.parts is None:
                port = opened_now.decl.web_port
                msg = f"port {port} is held by another program: the cards are not served here"
                raise NotReady(msg)
            return opened_now.parts

    def port(self) -> int | None:
        """Return the cards port this process serves, if it serves one."""
        with self._lock:
            served = self._open is not None and self._open.parts is not None
            return self._open.decl.web_port if served and self._open is not None else None

    def close(self) -> None:
        """Close whatever is open."""
        with self._lock:
            self._close()

    def _current(self) -> _Open:
        setup = self.setup()
        if setup.decl is None:
            raise NotReady(setup.problem or "no declaration yet")
        if setup.problem is not None:
            raise NotReady(setup.problem)
        if setup.found is None:
            msg = f"the variable {setup.decl.dsn_env} is not set"
            raise NotReady(msg)
        stamp = (
            self._place.config.stat().st_mtime_ns,
            hashlib.sha256(setup.found.dsn.encode()).hexdigest(),
        )
        if self._open is not None and self._open.stamp == stamp:
            return self._open
        self._close()
        self._open = self._start(stamp, setup.decl, setup.found.dsn)
        return self._open

    def _start(self, stamp: tuple[int, str], decl: Declaration, dsn: str) -> _Open:
        config = self._place.config
        try:
            key = self._key()
            gateway = checked_gateway(config, decl, dsn, key)
        except (RuntimeError, ValueError, StartError) as exc:  # fixed, safe lines
            raise NotReady(str(exc)) from None
        for line in protection_warnings(decl):
            sys.stderr.write(f"incognito-sql: {line}\n")
        parts: WebParts | None = None
        web: LocalWeb | None = None
        sock = bind_local(decl.web_port) if decl.web_enabled else None
        if sock is not None:
            try:
                parts = opened(lambda: open_cards(config, decl, dsn, key), sock)
            except StartError:
                gateway.close()
                raise
            web = LocalWeb(parts, sock)
            web.start()
        return _Open(stamp, decl, gateway, parts, web)

    def _close(self) -> None:
        if self._open is None:
            return
        if self._open.web is not None:
            self._open.web.stop()
        self._open.gateway.close()
        self._open = None
