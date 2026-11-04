from collections.abc import Iterator
from pathlib import Path

import pytest

from incognito_sql.core.budget import LiteralBudget
from incognito_sql.core.config import ColumnClass, Declaration, Entity, Limits
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.store import TokenStore


@pytest.fixture
def budget(tmp_path: Path) -> Iterator[LiteralBudget]:
    b = LiteralBudget(tmp_path / "t.db", Cipher(bytes(range(32))), Limits(literal_budget=20))
    yield b
    b.close()


@pytest.fixture
def store(tmp_path: Path) -> Iterator[TokenStore]:
    s = TokenStore(tmp_path / "tokens.db", Cipher(bytes(range(32))), "inst:db", ttl_s=24 * 3600)
    yield s
    s.close()


CATALOG = Catalog(columns={"people": {"id": "INTEGER", "full_name": "TEXT"}})
DECL = Declaration(
    dsn_env="DB_DSN",
    dialect="postgres",
    columns={"people": {"id": ColumnClass.OPEN, "full_name": ColumnClass.IDENTIFIER}},
    entities=[Entity(table="people", pk="id")],
)
