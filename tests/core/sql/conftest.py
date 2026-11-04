import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlglot.optimizer.qualify import qualify

from incognito_sql.core.config import ColumnClass, Declaration, Entity, Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.allowlist import check_nodes
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.policy import PolicyResult, enforce
from incognito_sql.core.sql.resolve import qualify_tree
from incognito_sql.core.sql.rewrite import Prepared, prepare
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.store import TokenStore


@pytest.fixture
def people_db(tmp_path: Path) -> Path:
    path = tmp_path / "people.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT,"
        " phone BIGINT, city TEXT, notes TEXT)"
    )
    con.execute("CREATE VIEW cities AS SELECT DISTINCT city FROM people")
    con.execute("INSERT INTO people VALUES (1, 'Ivan Petrov', 5550101, 'Zqtown', 'n1')")
    con.commit()
    con.close()
    return path


PolicyRun = Callable[..., PolicyResult | Reason]
Outcome = Reason | tuple[list[int], int, int]

DIALECTS = ["postgres", "sqlite"]


def summary(result: PolicyResult | Reason) -> Outcome:
    """Reduce a result to (pii_outputs, #literals, #tokens), or keep the Reason."""
    if isinstance(result, Reason):
        return result
    return (result.pii_outputs, len(result.pii_literals), len(result.pii_tokens))


CATALOG = Catalog(
    columns={
        "people": {
            "id": "INTEGER",
            "full_name": "TEXT",
            "phone": "BIGINT",
            "city": "TEXT",
            "notes": "TEXT",
        },
        "orders": {"id": "INTEGER", "customer_name": "TEXT", "note": "TEXT", "amount": "NUMERIC"},
        "audit_shadow": {"a": "TEXT", "b": "TEXT", "c": "TEXT"},
    }
)

SCHEMA: dict[str, object] = {table: dict(cols) for table, cols in CATALOG.columns.items()}

DECL = Declaration(
    dsn_env="DB_DSN",
    dialect="postgres",
    columns={
        "people": {
            "id": ColumnClass.OPEN,
            "full_name": ColumnClass.IDENTIFIER,
            "phone": ColumnClass.IDENTIFIER,
            "city": ColumnClass.QUASI,
        },
        "orders": {
            "id": ColumnClass.OPEN,
            "customer_name": ColumnClass.IDENTIFIER,
            "note": ColumnClass.OPEN,
            "amount": ColumnClass.OPEN,
        },
    },
    entities=[Entity(table="people", pk="id")],
    protection="strict",
)


@pytest.fixture
def policy() -> PolicyRun:
    """Run the pipeline parse -> check_nodes -> qualify_tree -> enforce.

    Returns the PolicyResult, or the Reason of the first rejection. With
    `nodes=False` the allowlist is skipped, to test the policy on its own.
    """

    def _run(  # noqa: PLR0913
        sql: str,
        dialect: str,
        *,
        nodes: bool = True,
        placeholders: bool = False,
        decl: Declaration = DECL,
        catalog: Catalog = CATALOG,
    ) -> PolicyResult | Reason:
        try:
            tree = parse(sql, dialect, Limits())
            if nodes:
                check_nodes(tree, allow_placeholders=placeholders)
                qualified = qualify_tree(tree, catalog, dialect)
            else:  # the policy alone, past every allowlist
                qualified = qualify(tree, schema=SCHEMA, dialect=dialect, expand_stars=False)
            return enforce(qualified, catalog, decl, allow_placeholders=placeholders)
        except Rejection as exc:
            return exc.reason

    return _run


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
PrepareRun = Callable[..., Prepared]


@pytest.fixture
def store(tmp_path: Path) -> Iterator[TokenStore]:
    s = TokenStore(tmp_path / "tokens.db", Cipher(bytes(range(32))), "inst:db", ttl_s=24 * 3600)
    yield s
    s.close()


@pytest.fixture
def prepare_sql(store: TokenStore) -> PrepareRun:
    """Run the whole chain up to `prepare`; a Rejection propagates."""

    def _run(sql: str, dialect: str = "postgres", decl: Declaration = DECL) -> Prepared:
        decl = decl.model_copy(update={"dialect": dialect})
        tree = parse(sql, dialect, decl.limits)
        check_nodes(tree)
        qualified = qualify_tree(tree, CATALOG, dialect)
        result = enforce(qualified, CATALOG, decl)
        return prepare(qualified, result, store, CATALOG, decl, NOW)

    return _run
