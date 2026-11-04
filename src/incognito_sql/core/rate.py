"""How many queries the installation answers per window: it slows a search down.

Every query counts, refused or not, before it is parsed. The count is kept in the token
store, so every server process of the installation shares one window. A brake on
probing, not a bound on what is learned: the literal budget is that.
"""

from datetime import datetime
from pathlib import Path

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.tokens.db import Tx, connect, epoch

_SCHEMA = """
CREATE TABLE IF NOT EXISTS query_hits (at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS query_hits_at ON query_hits (at);
"""


class QueryRate:
    """At most ``query_rate`` queries per sliding ``query_window_s`` across the installation."""

    def __init__(self, store_path: Path, limits: Limits) -> None:
        """Open or create the table in the token store file."""
        self._rate = limits.query_rate
        self._window = limits.query_window_s
        self._con = connect(store_path)
        self._con.executescript(_SCHEMA)

    def hit(self, now: datetime) -> None:
        """Count one query, or raise ``Rejection(RATE_LIMIT)`` and count nothing."""
        at = epoch(now)
        with Tx(self._con):
            self._con.execute("DELETE FROM query_hits WHERE at <= ?", (at - self._window,))
            (seen,) = self._con.execute("SELECT count(*) FROM query_hits").fetchone()
            over = seen >= self._rate
            if not over:
                self._con.execute("INSERT INTO query_hits (at) VALUES (?)", (at,))
        if over:
            raise Rejection(Reason.RATE_LIMIT)

    def close(self) -> None:
        """Close the connection."""
        self._con.close()
