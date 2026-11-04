"""How a competitor process starts: a container beside the database.

A container joins the DBMS container's network (a sidecar), so it reaches the database
on ``localhost``; a SQLite file is mounted read-only. Images are built here from a
Dockerfile of ours (which installs the published package) or from the competitor's own
repository at a pinned commit, cloned into a cache outside the repository.
"""

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from mcp import StdioServerParameters

from bench.adapters.base import NotRunError
from bench.dbms import Database

DOCKERFILES = Path(__file__).parent / "docker"
CONFIG = Path(__file__).parent / "config"
CACHE = Path(os.environ.get("BENCH_CACHE", Path.home() / ".cache" / "incognito-bench"))
_BUILD_TIMEOUT = 1800
Prepare = tuple[str, str] | None


def tool(name: str) -> str:
    """Return the full path of a command on PATH, or raise ``NotRunError``."""
    found = shutil.which(name)
    if found is None:
        msg = f"{name} is not installed"
        raise NotRunError(msg)
    return found


def container(
    image: str,
    db: Database,
    env: Mapping[str, str],
    mounts: Mapping[Path, str] | Mapping[Path | str, str],
    args: list[str],
) -> StdioServerParameters:
    """Return ``docker run`` of ``image`` beside ``db``; ``env`` values pass by name only.

    A mount source is a host path, or a docker volume when given as a string.
    """
    line = ["run", "-i", "--rm", *owner()]
    if db.container:
        line += ["--network", f"container:{db.container}"]
    for key in env:
        line += ["-e", key]
    for source, target in mounts.items():
        where = source if isinstance(source, str) else source.resolve().as_posix()
        line += ["-v", f"{where}:{target}"]
    return StdioServerParameters(
        command=tool("docker"), args=[*line, image, *args], env={**os.environ, **env}
    )


def owner() -> list[str]:
    """Return ``--user`` as this process's ids on POSIX, so files a container writes stay ours."""
    uid, gid = getattr(os, "getuid", None), getattr(os, "getgid", None)
    return [] if uid is None or gid is None else ["--user", f"{uid()}:{gid()}"]


def ensure_image(
    tag: str, *, dockerfile: str = "", repo: str = "", sha: str = "", prepare: Prepare = None
) -> str:
    """Get ``tag`` once: build our Dockerfile, build ``repo`` at ``sha``, or pull it.

    ``prepare`` is (image, shell line) run in a throwaway container on the checkout
    before its own Dockerfile builds, for a repository whose Dockerfile expects a build
    output. Any failed step stops here: nothing is built from another commit.
    """
    docker = tool("docker")
    if _quiet([docker, "image", "inspect", tag]):
        return tag
    if dockerfile:
        recipe = str(DOCKERFILES / dockerfile)
        _step([docker, "build", "-q", "-t", tag, "-f", recipe, str(DOCKERFILES)], tag, "build")
    elif not repo:
        _step([docker, "pull", "-q", tag], tag, "pull")
    else:
        checkout = CACHE / tag.replace(":", "-").replace("/", "-")
        if not checkout.exists():
            _step([tool("git"), "clone", "-q", repo, str(checkout)], tag, "clone")
        _step([tool("git"), "-C", str(checkout), "checkout", "-q", sha], tag, "checkout")
        if prepare:
            image, line = prepare
            mount = f"{checkout.resolve().as_posix()}:/src"
            run = [docker, "run", "--rm", "-v", mount, "-w", "/src", image, "sh", "-c", line]
            _step(run, tag, "prepare")
        _step([docker, "build", "-q", "-t", tag, str(checkout)], tag, "build")
    return tag


def _step(command: list[str], tag: str, what: str) -> None:
    if not _quiet(command):
        msg = f"image {tag}: {what} failed"
        raise NotRunError(msg)


def _quiet(command: list[str]) -> bool:
    done = subprocess.run(  # noqa: S603 -- fixed commands, no shell
        command, capture_output=True, check=False, timeout=_BUILD_TIMEOUT
    )
    return done.returncode == 0
