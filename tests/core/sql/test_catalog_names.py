"""Catalog names: the case the DBMS keeps, lookups in any case, case twins left out."""

from pathlib import Path

import duckdb
import pytest
from sqlalchemy import Engine

from incognito_sql.core.db import make_engine
from incognito_sql.core.sql import catalog as catalog_module
from incognito_sql.core.sql.catalog import Catalog, reflect, resolved


class _Inspector:
    """Tables as a case-keeping DBMS reports them."""

    tables = {  # noqa: RUF012 -- a fake
        "Clients": ["ClientId", "FullName", "fullname"],
        "Twin": ["id"],
        "twin": ["id"],
        "people": ["id"],
    }

    def get_table_names(self) -> list[str]:
        return [t for t in self.tables if t != "people"]

    def get_view_names(self) -> list[str]:
        return ["people"]

    def get_columns(self, table: str) -> list[dict[str, object]]:
        return [{"name": c, "type": "integer"} for c in self.tables[table]]


@pytest.mark.parametrize(
    ("dialect", "clients", "client_id"),
    [("postgres", "Clients", "ClientId"), ("mysql", "Clients", "ClientId")]
    + [(d, "clients", "clientid") for d in ("sqlite", "tsql")],
)
def test_reflect_keeps_case_where_the_dbms_does(
    monkeypatch: pytest.MonkeyPatch, dialect: str, clients: str, client_id: str
) -> None:
    monkeypatch.setattr(catalog_module, "inspect", lambda _engine: _Inspector())
    monkeypatch.setattr(catalog_module, "_parents", lambda *_: {})  # no database behind
    found = reflect(Engine.__new__(Engine), dialect)
    assert dict(found.columns[clients]) == {client_id: "INTEGER"}  # FullName twins dropped
    assert set(found.columns) == {clients, "people"}  # Twin and twin dropped
    assert found.table("CLIENTS") == clients
    assert found.column(clients, "CLIENTID") == client_id
    assert found.column(clients, "fullname") is None
    assert found.table("twin") is None


class _InternalsInspector(_Inspector):
    """An inspector that also lists SQLite's own tables."""

    tables = {"people": ["id"], "sqlite_sequence": ["name", "seq"]}  # noqa: RUF012 -- a fake

    def get_table_names(self) -> list[str]:
        return list(self.tables)

    def get_view_names(self) -> list[str]:
        return []


def test_reflect_skips_sqlite_internals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog_module, "inspect", lambda _engine: _InternalsInspector())
    assert set(reflect(Engine.__new__(Engine), "sqlite").columns) == {"people"}


def test_resolved_name_per_dialect() -> None:
    assert resolved("FullName", "postgres") == "FullName"
    assert resolved("FullName", "sqlite") == "fullname"


def test_lookup_on_a_missing_table() -> None:
    assert Catalog(columns={}).column("nope", "x") is None


def test_duckdb_columns_come_from_information_schema(tmp_path: Path) -> None:
    path = tmp_path / "w.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute('CREATE TABLE "Clients" ("ClientId" INTEGER, amount DECIMAL(10, 2))')
    engine = make_engine(f"duckdb:///{path.as_posix()}", "duckdb")
    try:
        found = reflect(engine, "duckdb")
    finally:
        engine.dispose()
    assert dict(found.columns["clients"]) == {"clientid": "INTEGER", "amount": "DECIMAL(10,2)"}
