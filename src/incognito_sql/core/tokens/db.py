"""SQLite connection and schema for the token dictionary."""

import sqlite3
from datetime import datetime
from importlib import resources
from pathlib import Path

BUSY_TIMEOUT_MS = 10_000


def epoch(moment: datetime) -> int:
    """Return the whole seconds of an aware datetime, as the dictionary stores time."""
    if moment.tzinfo is None:
        msg = "datetime must be timezone-aware"
        raise ValueError(msg)
    return int(moment.timestamp())


def connect(path: Path) -> sqlite3.Connection:
    """Open the dictionary file in WAL mode, creating the schema if needed.

    Transactions are explicit (``BEGIN IMMEDIATE``), so the connection is in
    autocommit mode otherwise.
    """
    con = sqlite3.connect(
        path, isolation_level=None, check_same_thread=False, timeout=BUSY_TIMEOUT_MS / 1000
    )
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    schema = resources.files("incognito_sql.core.tokens").joinpath("schema.sql").read_text("utf-8")
    con.executescript(schema)
    return con


class Tx:
    """``BEGIN IMMEDIATE`` ... commit, or rollback on error."""

    def __init__(self, con: sqlite3.Connection) -> None:
        """Wrap a connection in autocommit mode."""
        self._con = con

    def __enter__(self) -> None:
        """Start a write transaction."""
        self._con.execute("BEGIN IMMEDIATE")

    def __exit__(self, exc_type: object, *_: object) -> None:
        """Commit on success; roll back on error or failed commit."""
        if not exc_type:
            try:
                self._con.execute("COMMIT")
            except sqlite3.Error:
                self._rollback()
                raise
            return
        self._rollback()

    def _rollback(self) -> None:
        if self._con.in_transaction:
            self._con.execute("ROLLBACK")
