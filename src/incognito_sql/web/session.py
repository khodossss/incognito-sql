"""One-time login codes and browser sessions, kept as keyed digests in the token store."""

import secrets
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.db import Tx, connect

CODE_TTL_S = 5 * 60
SESSION_TTL_S = 8 * 3600
_SECRET_BYTES = 32
_SCHEMA = """
CREATE TABLE IF NOT EXISTS web_login_code (mac BLOB PRIMARY KEY, expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS web_session (mac BLOB PRIMARY KEY, expires_at INTEGER NOT NULL);
"""


def cookie_name(port: int) -> str:
    """Return the session cookie name for a web on this port (cookies ignore ports)."""
    return f"incognito_session_{port}"


class LoginRefused(Exception):  # noqa: N818
    """The login code is unknown, already used or expired."""


def _now() -> datetime:
    return datetime.now(UTC)


class Sessions:
    """Issues one-time codes and exchanges them for session cookies.

    The file is shared: one process may issue a code that another exchanges.
    Only keyed digests of codes and cookies are stored, never the secrets.
    """

    def __init__(
        self,
        path: Path,
        cipher: Cipher,
        clock: Callable[[], datetime] = _now,
        session_ttl_s: int = SESSION_TTL_S,
    ) -> None:
        """Open or create the tables in the token store file."""
        self._cipher = cipher
        self._clock = clock
        self._session_ttl_s = session_ttl_s
        self._lock = threading.RLock()
        self._con = connect(path)
        self._con.executescript(_SCHEMA)

    def issue_code(self) -> str:
        """Return a fresh random login code that lives five minutes."""
        code = secrets.token_urlsafe(_SECRET_BYTES)
        at = self._epoch()
        with self._lock, Tx(self._con):
            self._prune(at)
            self._con.execute(
                "INSERT INTO web_login_code (mac, expires_at) VALUES (?,?)",
                (self._mac("code", code), at + CODE_TTL_S),
            )
        return code

    def exchange(self, code: str) -> str:
        """Spend a live code and return a new session cookie value, else ``LoginRefused``."""
        at = self._epoch()
        cookie = secrets.token_urlsafe(_SECRET_BYTES)
        with self._lock, Tx(self._con):
            spent = self._con.execute(
                "DELETE FROM web_login_code WHERE mac=? AND expires_at > ?",
                (self._mac("code", code), at),
            ).rowcount
            if spent == 1:
                self._con.execute(
                    "INSERT INTO web_session (mac, expires_at) VALUES (?,?)",
                    (self._mac("session", cookie), at + self._session_ttl_s),
                )
        if spent != 1:
            raise LoginRefused
        return cookie

    def valid(self, cookie: str) -> bool:
        """Return True while the session behind a cookie value lives."""
        with self._lock:
            row = self._con.execute(
                "SELECT 1 FROM web_session WHERE mac=? AND expires_at > ?",
                (self._mac("session", cookie), self._epoch()),
            ).fetchone()
        return row is not None

    def close(self) -> None:
        """Close the database connection."""
        self._con.close()

    def _epoch(self) -> int:
        return int(self._clock().timestamp())

    def _mac(self, kind: str, secret: str) -> bytes:
        return self._cipher.mac(f"web {kind}:{secret}")

    def _prune(self, at: int) -> None:
        self._con.execute("DELETE FROM web_login_code WHERE expires_at <= ?", (at,))
        self._con.execute("DELETE FROM web_session WHERE expires_at <= ?", (at,))
