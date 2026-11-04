"""Column names with spaces, parentheses and hyphens pass the re-check; bind marks do not."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa

from incognito_sql.core.config import ColumnClass, Declaration
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.allowlist import check_nodes
from incognito_sql.core.sql.catalog import reflect
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.policy import enforce
from incognito_sql.core.sql.resolve import qualify_tree
from incognito_sql.core.sql.rewrite import prepare
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.store import TokenStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)
NAMES = ["Enrollment (K-12)", "School Name", "a:b", "c%d"]


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[sa.Engine]:
    eng = sa.create_engine(f"sqlite:///{tmp_path / 's.db'}")
    cols = ", ".join(f'"{n}" TEXT' for n in NAMES)
    with eng.begin() as con:
        con.exec_driver_sql(f"CREATE TABLE frpm (id INTEGER PRIMARY KEY, {cols})")
    yield eng
    eng.dispose()


def _prepare(sql: str, engine: sa.Engine, tmp_path: Path) -> str:
    catalog = reflect(engine, "sqlite")
    decl = Declaration(
        dsn_env="X",
        dialect="sqlite",
        columns={"frpm": {"id": ColumnClass.OPEN, **dict.fromkeys(NAMES, ColumnClass.OPEN)}},
        entities=[],
    )
    store = TokenStore(tmp_path / "t.db", Cipher(bytes(range(32))), "i:d", ttl_s=60)
    try:
        tree = parse(sql, "sqlite", decl.limits)
        check_nodes(tree)
        qualified = qualify_tree(tree, catalog, "sqlite")
        return prepare(qualified, enforce(qualified, catalog, decl), store, catalog, decl, NOW).sql
    finally:
        store.close()


def test_spaced_names_pass(engine: sa.Engine, tmp_path: Path) -> None:
    sql = "SELECT `School Name`, `Enrollment (K-12)` FROM frpm ORDER BY `Enrollment (K-12)`"
    assert "school name" in _prepare(sql, engine, tmp_path).lower()


@pytest.mark.parametrize("name", ["a:b", "c%d"])
def test_names_with_bind_marks_stay_refused(name: str, engine: sa.Engine, tmp_path: Path) -> None:
    with pytest.raises(Rejection) as caught:
        _prepare(f'SELECT "{name}" FROM frpm', engine, tmp_path)  # noqa: S608
    assert caught.value.reason is Reason.NODE_NOT_ALLOWED
