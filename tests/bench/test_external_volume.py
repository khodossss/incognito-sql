"""The docker volume a set's file is copied to: made once per file, removed at the end."""

import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path

import pytest

from bench.adapters import launch
from bench.adapters.base import NotRunError
from bench.external import volume


def _docker(monkeypatch: pytest.MonkeyPatch, code: int) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command[1:])
        return subprocess.CompletedProcess(command, code)

    monkeypatch.setattr(launch, "tool", lambda _name: "docker")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    return calls


def test_a_file_is_copied_once_and_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _docker(monkeypatch, 0)
    path = tmp_path / "Shop.sqlite"
    path.touch()
    assert volume.volume(path) == volume.volume(path) == "incognito-ext-shop"
    assert [c[:2] for c in calls] == [["volume", "create"], ["run", "--rm"]]
    assert calls[1][-3:] == ["cp", "/src/Shop.sqlite", "/data/"]
    volume.remove_volumes()
    assert calls[-1] == ["volume", "rm", "-f", "incognito-ext-shop"]
    volume.remove_volumes()  # nothing left: no docker call
    assert len(calls) == 3


def test_a_failed_copy_is_not_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _docker(monkeypatch, 1)
    path = tmp_path / "shop.sqlite"
    path.touch()
    with pytest.raises(NotRunError, match="incognito-ext-shop: volume failed"):
        volume.volume(path)
    volume.remove_volumes()


def test_a_file_in_wal_mode_goes_over_in_the_rollback_mode(tmp_path: Path) -> None:
    path = tmp_path / "cards.sqlite"
    with closing(sqlite3.connect(path)) as con:
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("CREATE TABLE cards (artist TEXT)")
        con.execute("INSERT INTO cards VALUES ('Avel Quorin')")
        con.commit()
    with volume.rollback(path) as source:
        assert source != path
        assert source.name == path.name
        assert source.read_bytes()[18:20] == bytes((1, 1))
        with closing(sqlite3.connect(source)) as con:
            assert con.execute("SELECT artist FROM cards").fetchall() == [("Avel Quorin",)]
    assert not source.exists()
    plain = tmp_path / "plain.sqlite"
    sqlite3.connect(plain).close()
    with volume.rollback(plain) as source:
        assert source == plain


def test_a_volume_still_in_use_is_removed_once_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    busy = [2]  # the first two removals find the volume still in use

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command[1:])
        code = 0
        if command[1:3] == ["volume", "rm"] and busy[0]:
            busy[0] -= 1
            code = 1
        return subprocess.CompletedProcess(command, code)

    monkeypatch.setattr(launch, "tool", lambda _name: "docker")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    path = tmp_path / "shop.sqlite"
    path.touch()
    volume.volume(path)
    volume.remove_volumes()
    assert [c for c in calls if c[:2] == ["volume", "rm"]] == [
        ["volume", "rm", "-f", "incognito-ext-shop"]
    ] * 3
