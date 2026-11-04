"""The decoy copy: hidden values replaced alike everywhere, the rest kept."""

import sqlite3
from contextlib import closing
from pathlib import Path

from external_world import build

from bench.external.dbfile import opened
from bench.external.twin import decoy, decoy_copy, decoy_text


def test_decoys_keep_the_kind_and_equal_values_stay_equal() -> None:
    phone = 7182887233  # invented
    forged = decoy(phone)
    assert isinstance(forged, int)
    assert forged == decoy(phone) != phone
    assert len(str(forged)) == len(str(phone))
    assert all(a != b for a, b in zip(str(forged), str(phone), strict=True))  # no digit kept
    assert isinstance(decoy(2.5), float)
    assert decoy(2.5) != 2.5
    assert isinstance(decoy(-1e20), float)
    assert decoy("Avel") == decoy("Avel") != decoy("Avel ")
    assert isinstance(decoy("Avel"), str)
    assert decoy(b"\x00") != b"\x00"
    assert decoy(None) is None


def test_text_that_is_not_utf8_gets_a_decoy(tmp_path: Path) -> None:
    path = tmp_path / "latin.sqlite"
    with closing(sqlite3.connect(path)) as con:
        con.execute("CREATE TABLE p (name TEXT)")
        con.execute("INSERT INTO p VALUES (CAST(X'4DFC6C6C6572' AS TEXT)), ('Avel')")
        con.commit()
    copy = decoy_copy(path, tmp_path / "twin.sqlite", {("p", "name")})
    with opened(copy) as con:
        names = [n for (n,) in con.execute("SELECT name FROM p ORDER BY rowid")]
        kinds = {k for (k,) in con.execute("SELECT typeof(name) FROM p")}
    assert names == [decoy_text(b"M\xfcller"), decoy("Avel")]
    assert kinds == {"text"}


def test_the_copy_replaces_only_hidden_columns(tmp_path: Path) -> None:
    path, _ = build(tmp_path)
    with opened(path) as con:
        (table, column), *_ = [
            (t, c[1])
            for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            for c in con.execute(f'PRAGMA table_info("{t}")')
        ]
        before = con.execute(f'SELECT * FROM "{table}"').fetchall()  # noqa: S608
    copy = decoy_copy(path, tmp_path / "twin.sqlite", {(table.lower(), column.lower())})
    with opened(copy) as con:
        after = con.execute(f'SELECT * FROM "{table}"').fetchall()  # noqa: S608
    assert len(after) == len(before)
    assert [r[0] for r in after] == [decoy(r[0]) for r in before]
    assert [r[1:] for r in after] == [r[1:] for r in before]
