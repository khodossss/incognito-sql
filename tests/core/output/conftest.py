import random
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from incognito_sql.core.config import ColumnClass, Declaration
from incognito_sql.core.exec.run import Rows
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.store import TokenStore


@pytest.fixture
def decl() -> Declaration:
    return Declaration(
        dsn_env="DSN",
        dialect="postgres",
        columns={"people": {"name": ColumnClass.IDENTIFIER}},
        entities=[],
    )


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def rng() -> random.Random:
    return random.Random(7)  # noqa: S311


@pytest.fixture
def store(tmp_path: Path) -> Iterator[TokenStore]:
    s = TokenStore(tmp_path / "d.db", Cipher(bytes(range(32))), "inst:db", ttl_s=3600)
    yield s
    s.close()


ID = ColumnClass.IDENTIFIER
QUASI = ColumnClass.QUASI
OPEN = ColumnClass.OPEN


def rows(data: Sequence[tuple[object, ...]], *, truncated: bool = False) -> Rows:
    width = len(data[0]) if data else 0
    return Rows(columns=[f"c{i}" for i in range(width)], rows=list(data), truncated=truncated)


def out_rows(out: dict[str, object]) -> list[list[object]]:
    value = out["rows"]
    assert isinstance(value, list)
    return value


def labels_off(decl: Declaration) -> Declaration:
    return decl.model_copy(update={"web_enabled": False})
