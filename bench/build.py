"""Build a world in a SQLite or DuckDB file and watch the file for any write."""

import contextlib
import hashlib
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import duckdb

from bench.cases import Case
from bench.check import pool_sizes
from bench.world import World

Run = Callable[[str], list[tuple[object, ...]]]


@contextlib.contextmanager
def _connected(dialect: str, path: Path) -> Iterator[Run]:
    """Yield a statement runner on the file; SQLite commits when the block ends."""
    if dialect == "sqlite":
        con = sqlite3.connect(path)
        try:
            yield lambda sql: con.execute(sql).fetchall()
            con.commit()
        finally:
            con.close()
        return
    with duckdb.connect(str(path)) as duck:
        yield lambda sql: duck.execute(sql).fetchall()


def fill_file(dialect: str, path: Path, statements: Iterable[str]) -> None:
    """Run ``statements`` in the SQLite or DuckDB file ``path`` (created if missing)."""
    with _connected(dialect, path) as run:
        for statement in statements:
            run(statement)


def build_file(world: World, dialect: str, path: Path, cases: Iterable[Case]) -> dict[str, int]:
    """Create the world in ``path``; return the pool size of each order-sensitive case.

    Pools are counted on the building connection, before any gateway opens the file.
    """
    with _connected(dialect, path) as run:
        for statement in world.statements(dialect):
            run(statement)
        return pool_sizes(cases, run, dialect)


def file_state(path: Path) -> Callable[[], tuple[str, list[str]]]:
    """Return a reading of the file's bytes and of its journal or WAL companions."""

    def state() -> tuple[str, list[str]]:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest, sorted(p.name for p in path.parent.glob(f"{path.name}*"))

    return state
