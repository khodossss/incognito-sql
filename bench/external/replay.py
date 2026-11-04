"""Answers of the container competitors, kept on disk and replayed without Docker.

A competitor is not configured by us beyond the marking, so its answer to a query is
fixed by the tool's version, the side (the file or its decoy twin), the work (database,
marking, condition) and the sets' digests: the key of its record. Every answer and its
side channels are stored as the query runs; a later run reads them back and starts the
tool only for a query it has not seen.
incognito-sql is kept the same way, its key holding also the digests of the server's
code, of the installed packages and of its declaration, so no answer is read back once
one changes; raw SQL runs in process and is never replayed. A store opened to
``rescore`` starts no tool: a query it has not seen stops the run, so tables recounted
after a change of the oracle hold only the answers of the run they recount. ``VERSION``
changes when the way competitors are configured from the marking changes.
"""

import functools
import hashlib
import pickle
import sqlite3
import sys
from collections.abc import Callable, Mapping
from importlib import metadata
from pathlib import Path

from bench.adapters.base import ERROR, FOREIGN_TOKENS, Adapter, Info, NotRunError, Outcome
from bench.adapters.launch import CACHE
from bench.external import sources
from bench.external.work import Work

VERSION = 1
STORE = CACHE / "external" / "replay.sqlite"
_SERVER = Path(__file__).resolve().parents[2] / "src" / "incognito_sql"


class UnrecordedError(Exception):
    """A rescoring run met a query its store has no answer to."""


def key(info: Info, side: str, work: Work, setup: str = "") -> str:
    """Return the record key of ``info`` on one side of ``work``, ``setup`` its own config."""
    digests = [s.sha256 for s in (sources.SPIDER, sources.BIRD, sources.SECURESQL)]
    parts = [VERSION, info.name, info.version, side, repr(work.marking), *digests, setup]
    return hashlib.sha256(repr(parts).encode()).hexdigest()


@functools.cache
def server_code(root: Path = _SERVER) -> str:
    """Return the digest of the server's source files, path and content."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


@functools.cache
def installed() -> str:
    """Return the digest of Python's version and every installed package's version.

    The same server code answers otherwise under another sqlglot, SQLAlchemy or driver.
    """
    names = sorted({(d.metadata["Name"] or "", d.version) for d in metadata.distributions()})
    return hashlib.sha256(repr((sys.version, names)).encode()).hexdigest()


class Store:
    """Records by key and query; ``fresh`` writes without reading back, ``rescore`` only reads."""

    def __init__(
        self, path: Path | None = None, *, fresh: bool = False, rescore: bool = False
    ) -> None:
        """Open or create the store file, ``STORE`` by default."""
        path = path or STORE
        path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(path)
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS answer (key TEXT, kind TEXT, query TEXT,"
            " value BLOB, PRIMARY KEY (key, kind, query))"
        )
        self._fresh, self.rescore = fresh, rescore

    def get(self, key: str, kind: str, query: str) -> object | None:
        """Return the stored value, or None."""
        if self._fresh:
            return None
        row = self._con.execute(
            "SELECT value FROM answer WHERE key = ? AND kind = ? AND query = ?", (key, kind, query)
        ).fetchone()
        return None if row is None else pickle.loads(row[0])  # noqa: S301 -- written below

    def put(self, key: str, kind: str, query: str, value: object) -> None:
        """Store ``value``."""
        self._con.execute(
            "INSERT OR REPLACE INTO answer VALUES (?, ?, ?, ?)",
            (key, kind, query, pickle.dumps(value)),
        )
        self._con.commit()

    def close(self) -> None:
        """Close the file."""
        self._con.close()


class Replayed:
    """A competitor whose answers come from the store, the tool started only on a miss."""

    mode: str | None = None
    dialect = "sqlite"
    tokens: Mapping[str, str] = FOREIGN_TOKENS

    def __init__(
        self,
        info: Info,
        start: Callable[[], Adapter],
        store: Store,
        key: str,
        tool: Adapter | None = None,
    ) -> None:
        """Replay ``info``'s record ``key``; ``start`` opens the tool when needed."""
        self.info, self._start, self._store, self._key = info, start, store, key
        self._tool: Adapter | None = tool
        self._pending: dict[str, str] = {}

    def _open(self) -> Adapter:
        if self._store.rescore:
            msg = f"{self.info.name}: a query the store has no answer to; run without --rescore"
            raise UnrecordedError(msg)
        if self._tool is None:
            self._tool = self._start()
        return self._tool

    def query(self, sql: str) -> Outcome:
        """Return the stored answer to ``sql``, or ask the tool and store its answer."""
        hit = self._store.get(self._key, "query", sql)
        if not isinstance(hit, tuple):
            try:
                tool = self._open()
            except NotRunError as exc:
                return Outcome(ERROR, f"not run: {exc}", 0.0)
            hit = tool.query(sql), tool.channels()
            self._store.put(self._key, "query", sql, hit)
        out, self._pending = hit
        assert isinstance(out, Outcome)  # noqa: S101 -- the store holds what query() put
        return out

    def channels(self) -> dict[str, str]:
        """Return the side channels of the last answer."""
        pending, self._pending = self._pending, {}
        return pending

    def static(self) -> str:
        """Return the stored listing, or the tool's."""
        hit = self._store.get(self._key, "static", "")
        if hit is None:
            hit = self._open().static()
            self._store.put(self._key, "static", "", hit)
        return str(hit)

    def close(self) -> None:
        """Close the tool if it was started."""
        if self._tool is not None:
            self._tool.close()


def opened(info: Info, start: Callable[[], Adapter], store: Store, key: str) -> Replayed:
    """Return the replayed tool; start it now unless its record is there.

    A tool that cannot start raises ``NotRunError``, as it would unreplayed: a reason
    such as Docker not running is not the tool's, so a later run tries again. The reason
    is kept only for a rescore, which starts no tool and says why the run it recounts
    had none.
    """
    if store.get(key, "static", "") is not None:
        return Replayed(info, start, store, key)
    if store.rescore:
        reason = store.get(key, "skipped", "")
        raise NotRunError(str(reason) if reason is not None else "no answers kept for it")
    try:
        tool = start()
    except NotRunError as exc:
        store.put(key, "skipped", "", str(exc))
        raise
    return Replayed(tool.info, lambda: tool, store, key)
