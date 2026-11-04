"""The DBMS matrix: one world on five DBMS, a gateway on each as the SELECT-only reader."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp
from sqlglot.dialects.dialect import Dialect

from bench.dbms import Database, opened
from incognito_sql.core.config import load_declaration
from incognito_sql.core.pipeline import Gateway
from incognito_sql.wiring import audit_path, open_gateway

from .world import statements

# Spec order: Postgres, SQLite, MySQL, DuckDB, SQL Server.
DIALECTS = ["postgres", "sqlite", "mysql", "duckdb", "tsql"]
KEY = bytes(range(32))
CONFIG = """
dsn_env: INCOGNITO_TEST_DSN
dialect: {dialect}
columns:
  people: {{id: open, full_name: identifier, city: quasi, bio: free_text, phone: identifier}}
  orders: {{id: open, person_id: open, customer_name: identifier, amount: open}}
  cards: {{card_no: open, holder: identifier}}
  Clients: {{ClientId: open, FullName: identifier, Town: quasi}}
  wallets: {{id: open, m: identifier}}
  wide: {{id: open, num: identifier, m: identifier, i: identifier, sm: identifier,
          h: identifier, d: identifier, uh: identifier, b: identifier, ub: identifier,
          ui: identifier}}
  moments: {{id: open, ts: identifier, tz: identifier, seen: open}}
  probes: {{id: open, hi: identifier, neg: identifier, d12: identifier, dbl: identifier,
           txt: identifier, ub: identifier, uh: identifier, d10: identifier, f: identifier,
           dt: identifier, ts: identifier, tz: identifier, u: identifier, bo: identifier,
           e: identifier, num: identifier, mo: identifier, d40: identifier, du: identifier,
           dbu: identifier, d38: identifier, dt2: identifier, dtm: identifier,
           dto: identifier, sm: identifier, ib: identifier, ubi: identifier,
           dtf: identifier, fu: identifier}}
entities:
  - {{table: people, pk: id}}
  - {{table: Clients, pk: ClientId}}
"""


def _world(dialect: str) -> Iterator[Database]:
    with opened(dialect, statements(dialect)) as database:
        yield database


@pytest.fixture(scope="session")
def postgres_backend() -> Iterator[Database]:
    yield from _world("postgres")


@pytest.fixture(scope="session")
def mysql_backend() -> Iterator[Database]:
    yield from _world("mysql")


@pytest.fixture(scope="session")
def tsql_backend() -> Iterator[Database]:
    yield from _world("tsql")


@pytest.fixture(scope="session")
def sqlite_backend() -> Iterator[Database]:
    yield from _world("sqlite")


@pytest.fixture(scope="session")
def duckdb_backend() -> Iterator[Database]:
    yield from _world("duckdb")


@pytest.fixture(params=DIALECTS)
def backend(request: pytest.FixtureRequest) -> Database:
    found = request.getfixturevalue(f"{request.param}_backend")
    assert isinstance(found, Database)
    return found


@dataclass(frozen=True)
class Field:
    """A gateway opener on one backend, and where its files go."""

    backend: Database
    config: Path
    open: Callable[[str], Gateway]

    @property
    def audit(self) -> Path:
        return audit_path(self.config)

    def sql(self, postgres_sql: str) -> str:
        """The model's query, written for Postgres, as the model would write it natively.

        Sort keys get the target's own NULL order, so no emulation is generated.
        """
        dialect = self.backend.dialect
        tree = sqlglot.parse_one(postgres_sql, read="postgres")
        ordering = Dialect.get_or_raise(dialect).NULL_ORDERING
        for key in tree.find_all(exp.Ordered):
            first = "nulls_are_large" if key.args.get("desc") else "nulls_are_small"
            key.set("nulls_first", ordering == first)
        return tree.sql(dialect=dialect)


@pytest.fixture
def field(backend: Database, tmp_path: Path) -> Iterator[Field]:
    opened: list[Gateway] = []
    config = tmp_path / "field.yaml"

    def _open(extra: str = "") -> Gateway:
        config.write_text(CONFIG.format(dialect=backend.dialect) + extra, encoding="utf-8")
        gw = open_gateway(config, load_declaration(config), backend.url, KEY)
        opened.append(gw)
        return gw

    yield Field(backend, config, _open)
    for gw in opened:
        gw.close()


@pytest.fixture
def gateway(field: Field) -> Gateway:
    return field.open("")
