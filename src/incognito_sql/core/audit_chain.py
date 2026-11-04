"""The audit log as a chain: each line carries its number and a keyed digest of the last.

Several processes append to one log (``serve`` runs one per connection): reading the
last line and writing the next happen under a lock on a file beside the log. The
number and digest of the last line are kept in the token store too (the anchor), so a
cut tail is seen. The digest is keyed with the service's key: whoever edits the log
without it cannot write a chain that holds. A line from before the chain has neither
field.
"""

import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.db import Tx, connect

_LINK = "audit-chain|"
_NIBBLES = "abcdefghijklmnop"
_STEP = 1 << 16  # bytes read at a time, backwards, to find the log's last line
_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_head (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    n INTEGER NOT NULL,
    digest TEXT NOT NULL
);
"""


def link(cipher: Cipher, line: str) -> str:
    """Return the keyed digest of a line as the next line carries it.

    Written in letters only, a nibble a letter: a digest never reads as a number, so it
    never looks like a value (a phone, an account) to whoever searches the log for one.
    """
    return "".join(_NIBBLES[b >> 4] + _NIBBLES[b & 15] for b in cipher.mac(_LINK + line))


class Anchor:
    """The number and digest of the log's last line, kept in the token store."""

    def __init__(self, store_path: Path) -> None:
        """Open the token store file and create the table if missing."""
        self._con = connect(store_path)
        self._con.executescript(_SCHEMA)

    def set(self, n: int, digest: str) -> None:
        """Record the last line written."""
        with Tx(self._con):
            self._con.execute(
                "INSERT INTO audit_head (id, n, digest) VALUES (1, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET n = excluded.n, digest = excluded.digest",
                (n, digest),
            )

    def get(self) -> tuple[int, str] | None:
        """Return the number and digest of the last line written, if any."""
        row = self._con.execute("SELECT n, digest FROM audit_head WHERE id = 1").fetchone()
        return None if row is None else (int(row[0]), str(row[1]))

    def close(self) -> None:
        """Close the connection."""
        self._con.close()


class Chain:
    """What the next line of a log carries, and where its head is kept."""

    def __init__(self, cipher: Cipher, anchor: Anchor) -> None:
        """Link with ``cipher``'s key; keep the head in ``anchor``."""
        self._cipher = cipher
        self._anchor = anchor

    def next(self, log: Path) -> tuple[int, str]:
        """Return the number and the link of the line to append to ``log``."""
        last = last_line(log)
        n = 0
        if last is not None:
            try:
                n = int(json.loads(last)["n"]) + 1
            except (ValueError, KeyError, TypeError):
                n = 0  # the line before the chain began, or not one of ours
        return n, link(self._cipher, last or "")

    def wrote(self, n: int, line: str) -> None:
        """Record ``line``, number ``n``, as the head of the log."""
        self._anchor.set(n, link(self._cipher, line))

    def close(self) -> None:
        """Close the anchor."""
        self._anchor.close()


def last_line(path: Path) -> str | None:
    """Return the last line of the file, without its line break, or None if empty.

    The file is read backwards until the line break before the last line, however long
    that line is: a query names its columns in its line, so a line has no fixed bound.
    """
    chunks: list[bytes] = []  # of the last line, from its end; joined once
    try:
        with path.open("rb") as fh:
            end = fh.seek(0, os.SEEK_END)
            while end > 0:
                start = max(0, end - _STEP)
                fh.seek(start)
                chunk = fh.read(end - start)
                end = start
                if not chunks:  # the file's own trailing line breaks are no line
                    chunk = chunk.rstrip(b"\r\n")
                    if not chunk:
                        continue
                cut = chunk.rfind(b"\n")
                chunks.append(chunk[cut + 1 :])
                if cut >= 0:
                    break
    except FileNotFoundError:
        return None
    last = b"".join(reversed(chunks)).rstrip(b"\r")
    return last.decode("utf-8") if last else None


@contextmanager
def locked(log: Path) -> Iterator[None]:
    """Hold a lock beside ``log`` that every writing process takes."""
    fd = os.open(log.with_name(log.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if sys.platform == "win32":
            import msvcrt  # noqa: PLC0415 -- the platform's own locking

            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl  # noqa: PLC0415 -- the platform's own locking

            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
