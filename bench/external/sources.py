"""The independent sets: pinned addresses and digests, downloaded into the bench cache.

Nothing of these sets is in the repository. Each file is fetched once into
``$BENCH_CACHE/external`` and checked against its SHA-256; a file that does not match is
an error, never used. A database inside an archive is extracted next to it on first use.
"""

import hashlib
import shutil
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bench.adapters.launch import CACHE

HOME = CACHE / "external"
_CHUNK = 1 << 20
_TIMEOUT_S = 600


@dataclass(frozen=True)
class Source:
    """One downloadable file of a set, as published."""

    name: str
    url: str
    sha256: str
    file: str


SPIDER = Source(
    "Spider 1.0",
    "https://drive.usercontent.google.com/download?id=1403EGqzIDoHMdQF4c9Bkyl7dZLZ5Wt6J"
    "&export=download&confirm=t",
    "00636695dabed6b5f4b8328a16b13e069a2f16591d5efcce57660669c85b121b",
    "spider_data.zip",
)
BIRD = Source(
    "BIRD Mini-Dev",
    "https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip",
    "cc48ba16838204e4e214512030cb572eeb5f7bcdd999bae4b9b6ff12ec13b92f",
    "minidev.zip",
)
SECURESQL = Source(
    "SecureSQL",
    "https://raw.githubusercontent.com/JacobiSong/SecureSQL/"
    "f00ba46378e43373fcbbfcdc9f8eca7299228845/data.json",
    "c0bf5fbc8d78577b30c56adfc4d4429ec490fa736e9f8f7ef46ba3ffeef6c6a4",
    "securesql-data.json",
)
# Where each set keeps its questions and its SQLite databases inside its archive.
SPIDER_QUESTIONS = "spider_data/dev.json"
SPIDER_DATABASES = "spider_data/database"
BIRD_QUESTIONS = "minidev/MINIDEV/mini_dev_sqlite.json"
BIRD_DATABASES = "minidev/MINIDEV/dev_databases"

Download = Callable[[str, Path], None]


class FetchError(Exception):
    """A set could not be downloaded, or its file is not the pinned one."""


def digest(path: Path) -> str:
    """Return the SHA-256 of a file, in hex."""
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            sha.update(chunk)
    return sha.hexdigest()


def fetch(source: Source, home: Path = HOME, download: Download | None = None) -> Path:
    """Return the cached file of ``source``, downloading it first if it is missing."""
    path = home / source.file
    if path.exists() and digest(path) == source.sha256:
        return path
    home.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    (download or _download)(source.url, part)
    got = digest(part)
    if got != source.sha256:
        part.unlink()
        msg = f"{source.name}: sha256 {got}, expected {source.sha256}"
        raise FetchError(msg)
    part.replace(path)
    return path


def member(archive: Path, name: str) -> Path:
    """Return a file of ``archive``, extracted next to it under the archive's stem."""
    target = archive.with_suffix("") / name
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as zf, zf.open(name) as src, target.open("wb") as out:
            shutil.copyfileobj(src, out, _CHUNK)
    return target


def _download(url: str, target: Path) -> None:
    if not url.startswith("https://"):
        msg = f"not an https address: {url}"
        raise FetchError(msg)
    request = urllib.request.Request(url, headers={"User-Agent": "incognito-bench"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as src, target.open("wb") as out:  # noqa: S310
            shutil.copyfileobj(src, out, _CHUNK)
    except OSError as exc:
        msg = f"{url}: {type(exc).__name__}: {exc}"
        raise FetchError(msg) from exc
