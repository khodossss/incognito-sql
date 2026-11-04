"""Quoted mixed-case names on every DBMS: query, labels, cards and init keep the real name."""

from datetime import UTC, datetime

import pytest

from incognito_sql.core.config import load_declaration
from incognito_sql.core.db import make_engine
from incognito_sql.core.pipeline import Gateway
from incognito_sql.core.sql.catalog import reflect
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.store import TokenStore
from incognito_sql.init.sampling import sample
from incognito_sql.web.cards import Cards
from incognito_sql.wiring import store_path, token_domain

from .conftest import KEY, Field
from .test_matrix import rows, token

pytestmark = pytest.mark.integration
CLIENT = 'SELECT "ClientId", "FullName", "Town" FROM "Clients" WHERE "FullName" = \'{}\''


def test_mixed_case_names_answer_and_follow_up(field: Field, gateway: Gateway) -> None:
    first = gateway.query(field.sql(CLIENT.format("Ivan Petrov")), "c1")
    [[pk, link, town]] = rows(first)
    assert (pk, town) == (7, "Haifa")
    again = gateway.query(field.sql(CLIENT.format(token(link))), "c1")
    assert rows(again) == rows(first)
    star = gateway.query(field.sql('SELECT * FROM "Clients" WHERE "ClientId" = 8'), "c1")
    columns = star["columns"]
    assert isinstance(columns, list)
    assert [str(c).casefold() for c in columns] == ["clientid", "fullname", "town"]


def test_labels_find_mixed_case_entity_keys(field: Field) -> None:
    gw = field.open("web_enabled: false\n")
    out = gw.query(field.sql('SELECT "FullName" FROM "Clients" WHERE "ClientId" = 7'), "c1")
    labels = out["labels"]
    assert isinstance(labels, dict)
    [keys] = labels.values()
    assert isinstance(keys, dict)
    assert {table.casefold(): found for table, found in keys.items()} == {
        "people": [1],
        "clients": [7],
    }


def test_cards_show_mixed_case_rows(field: Field) -> None:
    gw = field.open("")
    gw.close()
    decl = load_declaration(field.config)
    cipher = Cipher(KEY)
    engine = make_engine(field.backend.url, decl.dialect)
    store = TokenStore(
        store_path(field.config), cipher, token_domain(cipher, field.backend.url), None
    )
    try:
        cards = Cards(decl, store, engine, reflect(engine, decl.dialect))
        found = cards.value(store.tokenize("Ivan Petrov", datetime.now(UTC)))
        assert found is not None
        value, entity_rows = found
        assert value == "Ivan Petrov"
        shown = {(r.entity.casefold(), r.pk): dict(r.fields) for r in entity_rows}
        assert {k: {c.casefold(): v for c, v in f.items()} for k, f in shown.items()} == {
            ("people", 1): {
                "id": 1,
                "full_name": "Ivan Petrov",
                "city": "Haifa",
                "bio": "b1",
                "phone": 501234567,
            },
            ("clients", 7): {"clientid": 7, "fullname": "Ivan Petrov", "town": "Haifa"},
        }
    finally:
        store.close()
        engine.dispose()


def test_init_samples_mixed_case_columns(field: Field) -> None:
    engine = make_engine(field.backend.url, field.backend.dialect)
    try:
        catalog = reflect(engine, field.backend.dialect)
        found, missed = sample(engine, catalog, field.backend.dialect)
    finally:
        engine.dispose()
    # The world's edge timestamps (year 294276) lie beyond what a driver can return.
    assert {t for t, _ in missed} <= {"moments"}
    names = {(t.casefold(), c.casefold()): v for (t, c), v in found.items()}
    assert sorted(map(str, names["clients", "fullname"])) == ["Ivan Petrov", "Zqcanary Person"]
    assert len(names["people", "phone"]) == 3


def test_names_that_differ_only_in_case_are_unknown(field: Field, gateway: Gateway) -> None:
    if field.backend.dialect not in {"postgres", "mysql"}:
        pytest.skip("this DBMS folds the case of names")
    tables = gateway.describe()["tables"]
    assert isinstance(tables, dict)
    assert {t.casefold() for t in tables} & {"twin"} == set()
    out = gateway.query(field.sql('SELECT id FROM "Twin"'), "c1")
    assert out == {"error": "unknown_column", "sqlstate": None}
