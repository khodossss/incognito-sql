"""A set's SQLite file on a docker volume, copied once per file for every container tool.

A host folder mounted into Docker's VM (Windows, macOS) reads a large SQLite file a hundred
times slower, which turned every query into a timeout. ``remove_volumes`` drops them.

The volume is mounted read-only, and a file in WAL mode cannot be opened there by every
SQLite build (Python's says "unable to open database file"): such a file goes over in the
rollback journal mode, the same rows in another journal format.
"""

import sqlite3
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from bench.adapters import launch
from bench.adapters.base import NotRunError
from bench.external.dbfile import opened

# The busybox that bench/adapters/docker/dbmcp.Dockerfile pins: any image with `cp` copies.
COPIER = "busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec"
_WAL = 2  # header bytes 18 and 19 (write and read format versions) of a file in WAL mode
_TRIES, _WAIT_S = 30, 1.0  # a container exits within seconds of its tool closing
_VOLUMES: dict[str, bool] = {}  # volume -> filled; every one is removed at the end


def volume(path: Path) -> str:
    """Return a docker volume holding ``path`` as ``/<file name>``, made on first use."""
    name = f"incognito-ext-{path.stem.lower()}"
    if not _VOLUMES.get(name):
        docker = launch.tool("docker")
        _VOLUMES[name] = False
        with rollback(path) as source:
            mount = f"{source.parent.resolve().as_posix()}:/src:ro"
            copy = ["run", "--rm", "-v", mount, "-v", f"{name}:/data", COPIER]
            for step in (["volume", "create", name], [*copy, "cp", f"/src/{path.name}", "/data/"]):
                done = subprocess.run([docker, *step], capture_output=True, check=False)  # noqa: S603
                if done.returncode:
                    msg = f"volume {name}: {step[0]} failed"
                    raise NotRunError(msg)
        _VOLUMES[name] = True
    return name


@contextmanager
def rollback(path: Path) -> Iterator[Path]:
    """Yield ``path``, or a copy of it under the same name in the rollback journal mode."""
    with path.open("rb") as file:
        header = file.read(20)
    if header[18:20] != bytes((_WAL, _WAL)):
        yield path
        return
    with tempfile.TemporaryDirectory(prefix="incognito-ext-") as folder:
        copy = Path(folder) / path.name
        with opened(path) as con, closing(sqlite3.connect(copy)) as out:
            con.backup(out)
            out.execute("PRAGMA journal_mode = DELETE")
        yield copy


def remove_volumes() -> None:
    """Remove the volumes this run made.

    A closed tool's container (``--rm``) can still hold its volume for a moment, and a
    volume in use is not removed: each removal is tried again until it goes through.
    """
    docker = launch.tool("docker") if _VOLUMES else ""
    for name in sorted(_VOLUMES):
        drop = [docker, "volume", "rm", "-f", name]
        for _ in range(_TRIES):
            if subprocess.run(drop, capture_output=True, check=False).returncode == 0:  # noqa: S603
                break
            time.sleep(_WAIT_S)
    _VOLUMES.clear()
