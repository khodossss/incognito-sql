"""An end-to-end world: a SQLite file with people and orders, a config, a key."""

import base64
import re
import socket
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from incognito_sql.cli import open_gateway
from incognito_sql.core.config import load_declaration
from incognito_sql.core.pipeline import Gateway
from incognito_sql.wiring import audit_path

CANARY = "zqcanary"  # compared case-insensitively
DSN_ENV = "INCOGNITO_TEST_DSN"
TOKEN = re.compile(r"tk_[a-z2-7]{16}")
KEY = bytes(range(32))
_KEY = base64.b64encode(KEY).decode("ascii")
# Point the child's fd 2 at a file, then run the real entry point.
CHILD = (
    "import os, sys\n"
    "os.dup2(os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC), 2)\n"
    "from incognito_sql.cli import main\n"
    "sys.exit(main(sys.argv[2:]))\n"
)

CONFIG = f"""
dsn_env: {DSN_ENV}
dialect: sqlite
columns:
  people: {{id: open, full_name: identifier, city: quasi, bio: free_text}}
  orders: {{id: open, person_id: open, customer_name: identifier, amount: open}}
  cards: {{card_no: open, holder: identifier}}
entities:
  - {{table: people, pk: id}}
"""


@dataclass(frozen=True)
class World:
    """Paths of the database, the config and the files the server writes next to it."""

    db: Path
    config: Path

    @property
    def audit(self) -> Path:
        return audit_path(self.config)

    def write_config(self, extra: str = "") -> Path:
        self.config.write_text(CONFIG + extra, encoding="utf-8")
        return self.config


def _make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT, city TEXT,
                             bio TEXT, secret_note TEXT);
        INSERT INTO people VALUES (1, 'Ivan Petrov', 'Haifa', 'b1', 'Zzsecret one');
        INSERT INTO people VALUES (2, 'Anna Ivanova', 'Haifa', 'b2', 'n2');
        INSERT INTO people VALUES (3, 'Zqcanary Person', 'Eilat', 'Zqcanary bio', 'Zqcanary');
        CREATE TABLE orders (id INTEGER PRIMARY KEY, person_id INTEGER, customer_name TEXT,
                             amount NUMERIC);
        INSERT INTO orders VALUES (10, 1, 'Ivan Petrov', 100);
        INSERT INTO orders VALUES (11, 3, 'Zqcanary Person', 250);
        INSERT INTO orders VALUES (12, 3, 'zqcanary person', 5);
        CREATE TABLE cards (card_no TEXT PRIMARY KEY, holder TEXT);
        INSERT INTO cards VALUES ('4111111111111111', 'Zqcanary Person');
        INSERT INTO cards VALUES ('c-7', 'Zqcanary Person');
        CREATE TABLE staff (id INTEGER, login TEXT);
        INSERT INTO staff VALUES (1, 'Zqcanary admin');
        """
    )
    con.commit()
    con.close()


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    db = tmp_path / "people.db"
    _make_db(db)
    monkeypatch.setenv(DSN_ENV, f"sqlite:///{db}")
    monkeypatch.setenv("INCOGNITO_SQL_KEY", _KEY)
    w = World(db=db, config=tmp_path / "field.yaml")
    w.write_config()
    return w


# Every entity table: labels keep each table's keys apart; a card number key is dropped.
ALL_ENTITIES = """entities:
  - {table: people, pk: id}
  - {table: orders, pk: id}
  - {table: cards, pk: card_no}
"""
CARD_NO = "4111111111111111"

GatewayFactory = Callable[[str], Gateway]


@pytest.fixture
def make_gateway(world: World) -> Iterator[GatewayFactory]:
    """Open a gateway on the world's config with extra YAML appended."""
    opened: list[Gateway] = []

    def _open(extra: str = "") -> Gateway:
        path = world.write_config(extra)
        gw = open_gateway(path, load_declaration(path), f"sqlite:///{world.db}", KEY)
        opened.append(gw)
        return gw

    yield _open
    for gw in opened:
        gw.close()


@pytest.fixture
def gateway(make_gateway: GatewayFactory) -> Gateway:
    return make_gateway("")


@pytest.fixture
def free_port() -> int:
    """A port on 127.0.0.1 that was free a moment ago."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
