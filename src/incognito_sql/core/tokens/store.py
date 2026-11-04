"""Encrypted dictionary between values and tokens."""

import copy
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import cast

from incognito_sql.core.tokens.canon import canonical
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.db import Tx, connect, epoch
from incognito_sql.core.tokens.format import TOKEN_RE, new_token

_ISSUE_TRIES = 8  # 80 random bits: one collision is rare, eight in a row is a fault


class InvalidToken(Exception):  # noqa: N818
    """The token is unknown, forged, truncated, expired or from another domain."""


class TokenStore:
    """Maps values to random tokens within one domain; values are stored encrypted."""

    def __init__(self, path: Path, cipher: Cipher, domain: str, ttl_s: int | None) -> None:
        """Open or create the dictionary file; ``ttl_s=None`` means tokens never expire."""
        if ttl_s is not None and ttl_s <= 0:
            msg = "ttl_s must be positive or None"
            raise ValueError(msg)
        self._cipher = cipher
        self._domain = domain
        self._ttl = ttl_s
        self._lock = threading.RLock()
        self._con = connect(path)

    def masks(self) -> "TokenStore":
        """Return this file in the domain of masked open cells, closed with this store."""
        view = copy.copy(self)
        view._domain = f"{self._domain}:mask"  # noqa: SLF001 -- a view of this class
        return view

    def tokenize(self, value: object, now: datetime) -> str:
        """Return the live token for a value read from the database; remember its spelling."""
        # Only database output adds spellings.
        raw = str(value)
        with self._lock, self._tx():
            value_id = self._value_id(canonical(value), create=True)
            assert value_id is not None  # noqa: S101
            self._con.execute(
                "INSERT OR IGNORE INTO variant (value_id, domain, raw_hash, sealed_raw) "
                "VALUES (?,?,?,?)",
                (value_id, self._domain, self._cipher.mac(raw), self._cipher.seal(raw)),
            )
            return self._live_token(value_id, epoch(now))

    def token_for(self, value: object, now: datetime) -> str:
        """Return the live token for text the model wrote; its spelling is not remembered."""
        with self._lock, self._tx():
            value_id = self._value_id(canonical(value), create=True)
            assert value_id is not None  # noqa: S101
            return self._live_token(value_id, epoch(now))

    def variants(self, token: str, now: datetime) -> list[str]:
        """Return the raw forms behind a live token of this domain, else ``InvalidToken``."""
        at = epoch(now)
        value_id, issued = self._lookup(token)
        if self._ttl is not None and issued + self._ttl <= at:
            raise InvalidToken
        return self._raw_forms(value_id)

    def reveal(self, token: str) -> str:
        """Return the first raw form of a token of this domain, however old; else its canon."""
        value_id, _ = self._lookup(token)
        forms = self._raw_forms(value_id)
        if forms:
            return forms[0]
        with self._lock:
            row = self._con.execute("SELECT sealed_canon FROM value WHERE id=?", (value_id,))
            return self._cipher.open(bytes(row.fetchone()[0]))

    def variants_for_literal(self, literal: object) -> list[str]:
        """Return the literal itself plus every known raw form of the same value."""
        raw = str(literal)
        with self._lock:
            value_id = self._value_id(canonical(literal), create=False)
            known = self._raw_forms(value_id) if value_id is not None else []
        return list(dict.fromkeys([raw, *known]))

    def close(self) -> None:
        """Close the database connection."""
        self._con.close()

    def _tx(self) -> Tx:
        return Tx(self._con)

    def _value_id(self, canon: str, *, create: bool) -> int | None:
        digest = self._cipher.mac(canon)
        row = self._con.execute("SELECT id FROM value WHERE canon_hash=?", (digest,)).fetchone()
        if row:
            return int(row[0])
        if not create:
            return None
        cur = self._con.execute(
            "INSERT INTO value (canon_hash, sealed_canon) VALUES (?,?)",
            (digest, self._cipher.seal(canon)),
        )
        return cast("int", cur.lastrowid)  # `id` is the rowid: set by a successful INSERT

    def _live_token(self, value_id: int, at: int) -> str:
        floor = -1 if self._ttl is None else at - self._ttl
        row = self._con.execute(
            "SELECT token FROM token WHERE value_id=? AND domain=? AND issued_at > ? "
            "ORDER BY issued_at DESC, rowid DESC",
            (value_id, self._domain, floor),
        ).fetchone()
        return str(row[0]) if row else self._issue(value_id, at)

    def _issue(self, value_id: int, at: int) -> str:
        for _ in range(_ISSUE_TRIES):
            token = new_token()
            try:
                self._con.execute(
                    "INSERT INTO token (token, value_id, domain, issued_at) VALUES (?,?,?,?)",
                    (token, value_id, self._domain, at),
                )
            except sqlite3.IntegrityError:
                continue
            return token
        msg = "no free token after repeated collisions"
        raise RuntimeError(msg)

    def _lookup(self, token: str) -> tuple[int, int]:
        if not TOKEN_RE.match(token):
            raise InvalidToken
        with self._lock:
            row = self._con.execute(
                "SELECT value_id, issued_at FROM token WHERE token=? AND domain=?",
                (token, self._domain),
            ).fetchone()
        if row is None:
            raise InvalidToken
        return int(row[0]), int(row[1])

    def _raw_forms(self, value_id: int) -> list[str]:
        with self._lock:
            rows = self._con.execute(
                "SELECT sealed_raw FROM variant WHERE value_id=? AND domain=? ORDER BY id",
                (value_id, self._domain),
            ).fetchall()
        return [self._cipher.open(bytes(r[0])) for r in rows]
