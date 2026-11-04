from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.store import TokenStore


@pytest.fixture
def cipher() -> Cipher:
    return Cipher(bytes(range(32)))


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "d.db"


@pytest.fixture
def store(db_path: Path, cipher: Cipher) -> Iterator[TokenStore]:
    s = TokenStore(db_path, cipher, "inst:db", ttl_s=24 * 3600)
    yield s
    s.close()


@pytest.fixture
def other_domain_store(db_path: Path, cipher: Cipher) -> Iterator[TokenStore]:
    s = TokenStore(db_path, cipher, "inst:other", ttl_s=24 * 3600)
    yield s
    s.close()
