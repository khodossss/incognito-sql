"""A small world for the card web: a SQLite file, a declaration and the open parts."""

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine
from starlette.testclient import TestClient

from incognito_sql.core.budget import LiteralBudget
from incognito_sql.core.config import ColumnClass, Declaration, Entity, Limits
from incognito_sql.core.db import make_engine
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.store import TokenStore
from incognito_sql.web.app import build_app
from incognito_sql.web.session import Sessions, cookie_name

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
ID = ColumnClass.IDENTIFIER
DECL = Declaration(
    dsn_env="DSN",
    dialect="sqlite",
    columns={
        "people": {
            "id": ColumnClass.OPEN,
            "full_name": ID,
            "city": ColumnClass.QUASI,
            "bio": ColumnClass.FREE_TEXT,
            "pw_hash": ColumnClass.SECRET,
        },
        "orders": {"id": ColumnClass.OPEN, "customer_name": ID},
    },
    entities=[
        Entity(table="people", pk="id"),
        Entity(table="orders", pk="customer_name"),
    ],
    web_port=PORT,
    limits=Limits(literal_budget=1),
)


class Clock:
    """A settable clock for code and session lifetimes."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Parts:
    db: Path
    store: TokenStore
    sessions: Sessions
    budget: LiteralBudget
    engine: Engine
    clock: Clock


def _make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT, city TEXT, bio TEXT,
                             pw_hash TEXT, note TEXT);
        INSERT INTO people VALUES (1, 'Ivan Petrov', 'Haifa', 'likes chess', 'Zzhash1', 'Zznote1');
        INSERT INTO people VALUES (2, 'Anna <b>Ivanova</b>', 'Eilat', 'b2', 'Zzhash2', 'n2');
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_name TEXT);
        INSERT INTO orders VALUES (10, 'Ivan Petrov');
        """
    )
    con.commit()
    con.close()


@pytest.fixture
def parts(tmp_path: Path) -> Iterator[Parts]:
    db = tmp_path / "people.db"
    _make_db(db)
    cipher = Cipher(bytes(range(32)))
    tokens = tmp_path / "field.tokens.db"
    clock = Clock()
    made = Parts(
        db=db,
        store=TokenStore(tokens, cipher, "db:test", ttl_s=60),
        sessions=Sessions(tokens, cipher, clock=clock),
        budget=LiteralBudget(tokens, cipher, DECL.limits),
        engine=make_engine(f"sqlite:///{db}", "sqlite"),
        clock=clock,
    )
    yield made
    made.store.close()
    made.sessions.close()
    made.budget.close()
    made.engine.dispose()


@pytest.fixture
def client(parts: Parts) -> Iterator[TestClient]:
    app = build_app(DECL, parts.store, parts.engine, parts.sessions, parts.budget)
    with TestClient(app, base_url=BASE, follow_redirects=False) as c:
        yield c


@pytest.fixture
def cookie(parts: Parts) -> dict[str, str]:
    """Headers of a signed-in browser."""
    return {"cookie": f"{cookie_name(PORT)}={parts.sessions.exchange(parts.sessions.issue_code())}"}
