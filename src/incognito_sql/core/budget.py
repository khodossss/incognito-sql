"""Budget of distinct human literals a connection may probe against personal columns."""

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.tokens.canon import canonical
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.db import Tx, connect, epoch

_SCHEMA = """
CREATE TABLE IF NOT EXISTS budget_spend (
    connection_id TEXT NOT NULL,
    canon_mac BLOB NOT NULL,
    spent_at INTEGER NOT NULL,
    PRIMARY KEY (connection_id, canon_mac)
);
CREATE INDEX IF NOT EXISTS budget_spend_at ON budget_spend (spent_at);
CREATE TABLE IF NOT EXISTS budget_alarm (at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS probe_spend (spent_at INTEGER NOT NULL, n INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS probe_spend_at ON probe_spend (spent_at);
"""


# Prefix of an exact literal: a canonical form never begins with whitespace.
_EXACT = " "


# A connection without a session of its own: only the installation window counts it.
SESSIONLESS = ""


@dataclass(frozen=True)
class Spend:
    """What one query spent: literals new to the installation's window, and probes.

    A budget that is unlimited counts nothing, so its part is 0.
    """

    literals: int = 0
    probes: int = 0


class LiteralBudget:
    """Caps distinct literals per connection and per sliding window of the installation.

    Only keyed digests of the literals are stored, never the literals. A connection
    keeps its count for its life; a SESSIONLESS one has no count of its own.
    """

    def __init__(self, store_path: Path, cipher: Cipher, limits: Limits) -> None:
        """Open or create the tables in the token store file."""
        self._cipher = cipher
        self._cap = limits.literal_budget
        self._probe_cap = limits.probe_budget
        self._window = limits.literal_window_s
        self._lock = threading.RLock()
        self._con = connect(store_path)
        self._con.executescript(_SCHEMA)

    def spend(
        self,
        connection_id: str,
        literals: list[str],
        now: datetime,
        *,
        exact: Sequence[str] = (),
        probes: int = 0,
    ) -> Spend:
        """Count a query's new distinct literals and its L3 probes, both or neither.

        `literals` count by canonical form: `=` matches every spelling of a value alike.
        `exact` ones count as written: a probe (`<`, `LIKE`) compares the spelling, and
        each spelling answers differently. The two never share a unit. `probes` count
        in the installation's window against ``limits.probe_budget``: only their number,
        never an answer, since a refusal that followed the answers would itself tell
        them.

        Return what was spent. Raise ``Rejection(LITERAL_BUDGET)`` or
        ``Rejection(PROBE_BUDGET)`` and spend nothing when either cap is passed. A budget
        of 0 refuses at once, with ``LITERALS_OFF`` or ``PROBES_OFF`` and no alarm; an
        unlimited one counts nothing.
        """
        if self._cap == 0 and (literals or exact):
            raise Rejection(Reason.LITERALS_OFF)
        if self._probe_cap == 0 and probes > 0:
            raise Rejection(Reason.PROBES_OFF)
        at = epoch(now)
        digests = [*(canonical(v) for v in literals), *(f"{_EXACT}{v}" for v in exact)]
        macs = [] if self._cap is None else list(dict.fromkeys(map(self._cipher.mac, digests)))
        probes = 0 if self._probe_cap is None else probes
        if not macs and probes <= 0:
            return Spend()
        with self._lock, Tx(self._con):
            live = self._live(at)
            refusal = self._refusal(connection_id, macs, probes, at, live)
            if refusal is not None:  # the alarm is committed (one row, the latest), no spend
                self._alarm(at)
            else:
                # Past the window a sessionless spend counts nowhere.
                self._con.execute(
                    "DELETE FROM budget_spend WHERE connection_id=? AND spent_at <= ?",
                    (SESSIONLESS, at - self._window),
                )
                # A clock behind never moves a spend out of the window.
                self._con.executemany(
                    "INSERT INTO budget_spend (connection_id, canon_mac, spent_at) "
                    "VALUES (?,?,?) ON CONFLICT (connection_id, canon_mac) "
                    "DO UPDATE SET spent_at=MAX(spent_at, excluded.spent_at)",
                    [(connection_id, m, at) for m in macs],
                )
                if probes > 0:
                    self._con.execute(
                        "INSERT INTO probe_spend (spent_at, n) VALUES (?, ?)", (at, probes)
                    )
        if refusal is not None:
            raise Rejection(refusal)
        return Spend(len(set(macs) - live), probes)

    def _refusal(
        self, connection_id: str, macs: list[bytes], probes: int, at: int, live: set[bytes]
    ) -> Reason | None:
        if self._cap is not None and macs and self._over(connection_id, macs, live):
            return Reason.LITERAL_BUDGET
        if self._probe_cap is not None and probes > 0:
            self._con.execute("DELETE FROM probe_spend WHERE spent_at <= ?", (at - self._window,))
            used = self._con.execute("SELECT COALESCE(SUM(n), 0) FROM probe_spend").fetchone()[0]
            if used + probes > self._probe_cap:
                return Reason.PROBE_BUDGET
        return None

    def _alarm(self, at: int) -> None:
        last = self._con.execute("SELECT MAX(at) FROM budget_alarm").fetchone()[0]
        self._con.execute("DELETE FROM budget_alarm")
        self._con.execute("INSERT INTO budget_alarm (at) VALUES (?)", (max(at, last or at),))

    def alarm_active(self, now: datetime) -> bool:
        """Return True while the latest budget alarm is within the window."""
        floor = epoch(now) - self._window
        with self._lock:
            row = self._con.execute("SELECT 1 FROM budget_alarm WHERE at > ? LIMIT 1", (floor,))
            return row.fetchone() is not None

    def close(self) -> None:
        """Close the database connection."""
        self._con.close()

    def _live(self, at: int) -> set[bytes]:
        """Return the literals the installation's window holds at ``at``."""
        return {
            bytes(r[0])
            for r in self._con.execute(
                "SELECT DISTINCT canon_mac FROM budget_spend WHERE spent_at > ?",
                (at - self._window,),
            )
        }

    def _over(self, connection_id: str, macs: list[bytes], live: set[bytes]) -> bool:
        assert self._cap is not None  # noqa: S101 -- an unlimited budget counts nothing
        if connection_id == SESSIONLESS:
            own: set[bytes] = set()
        else:
            own = {
                bytes(r[0])
                for r in self._con.execute(
                    "SELECT canon_mac FROM budget_spend WHERE connection_id=?", (connection_id,)
                )
            }
        return len(own | set(macs)) > self._cap or len(live | set(macs)) > self._cap
