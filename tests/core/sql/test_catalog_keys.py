"""Primary keys in the catalog, and whether they can hold NULL."""

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from incognito_sql.core.sql.catalog import reflect


@pytest.fixture
def keyed(tmp_path: Path) -> Iterator[sa.Engine]:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'k.db'}")
    with engine.begin() as con:
        for ddl in (
            "CREATE TABLE loose (id int PRIMARY KEY, x TEXT)",
            "CREATE TABLE rowid_key (id INTEGER PRIMARY KEY, x TEXT)",
            "CREATE TABLE strict_key (id int NOT NULL PRIMARY KEY, x TEXT)",
            "CREATE TABLE pair (a TEXT NOT NULL, b INT NOT NULL, x TEXT, PRIMARY KEY (b, a))",
            "CREATE TABLE nokey (x TEXT)",
            "CREATE VIEW v AS SELECT id, x FROM rowid_key",
        ):
            con.exec_driver_sql(ddl)
    yield engine
    engine.dispose()


def test_sqlite_keys_and_their_nulls(keyed: sa.Engine) -> None:
    catalog = reflect(keyed, "sqlite")
    assert catalog.keys == {
        "loose": ("id",),
        "rowid_key": ("id",),
        "strict_key": ("id",),
        "pair": ("b", "a"),
    }
    assert catalog.null_free == {"rowid_key", "strict_key", "pair"}


def test_a_failing_key_lookup_leaves_no_key(
    keyed: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> list[tuple[str, bool]]:
        raise RuntimeError

    monkeypatch.setattr("incognito_sql.core.sql.catalog._sqlite_key", broken)
    catalog = reflect(keyed, "sqlite")
    assert catalog.keys == {}
    assert catalog.null_free == frozenset()


def test_a_desc_key_may_hold_null(tmp_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'd.db'}")
    with engine.begin() as con:
        con.exec_driver_sql("CREATE TABLE down (id INTEGER PRIMARY KEY DESC, x TEXT)")
        con.exec_driver_sql("CREATE TABLE norow (id INTEGER PRIMARY KEY, x TEXT) WITHOUT ROWID")
        con.exec_driver_sql("INSERT INTO down VALUES (NULL, 'a'), (NULL, 'b')")
        with pytest.raises(sa.exc.IntegrityError):  # WITHOUT ROWID keys are NOT NULL
            con.exec_driver_sql("INSERT INTO norow VALUES (NULL, 'a')")
    catalog = reflect(engine, "sqlite")
    engine.dispose()
    assert catalog.keys == {"down": ("id",), "norow": ("id",)}
    assert catalog.null_free == {"norow"}
