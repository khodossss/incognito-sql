"""Downloading a set: pinned digest, cache, extraction of one member."""

import hashlib
import zipfile
from pathlib import Path

import pytest

from bench.external import sources
from bench.external.sources import FetchError, Source, digest, fetch, member

BODY = b"invented set\n"
SOURCE = Source(
    "invented", "https://example.test/set.json", hashlib.sha256(BODY).hexdigest(), "set.json"
)


def _writer(body: bytes, calls: list[str]) -> sources.Download:
    def download(url: str, target: Path) -> None:
        calls.append(url)
        target.write_bytes(body)

    return download


def test_fetch_downloads_once_and_checks_the_digest(tmp_path: Path) -> None:
    calls: list[str] = []
    path = fetch(SOURCE, tmp_path, _writer(BODY, calls))
    assert path.read_bytes() == BODY
    assert digest(path) == SOURCE.sha256
    assert fetch(SOURCE, tmp_path, _writer(BODY, calls)) == path
    assert calls == [SOURCE.url]


def test_a_file_with_another_digest_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="sha256"):
        fetch(SOURCE, tmp_path, _writer(b"something else", []))
    assert list(tmp_path.iterdir()) == []


def test_member_extracts_one_file(tmp_path: Path) -> None:
    archive = tmp_path / "set.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("set/db/shop/shop.sqlite", b"not really sqlite")
    path = member(archive, "set/db/shop/shop.sqlite")
    assert path == tmp_path / "set" / "set" / "db" / "shop" / "shop.sqlite"
    assert path.read_bytes() == b"not really sqlite"
    assert member(archive, "set/db/shop/shop.sqlite") == path


def test_only_https_is_downloaded(tmp_path: Path) -> None:
    plain = Source("plain", "http://example.test/x", "0" * 64, "x")
    with pytest.raises(FetchError, match="https"):
        fetch(plain, tmp_path)


def test_the_pinned_sets_are_https() -> None:
    for source in (sources.SPIDER, sources.BIRD, sources.SECURESQL):
        assert source.url.startswith("https://")
        assert len(source.sha256) == 64
