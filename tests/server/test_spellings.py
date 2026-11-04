"""A model cannot plant spellings: only database output adds them, and a query uses few."""

import itertools
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from incognito_sql.core.pipeline import Gateway
from incognito_sql.core.tokens.crypto import Cipher
from incognito_sql.core.tokens.store import TokenStore
from incognito_sql.wiring import store_path, token_domain

from .conftest import KEY, TOKEN, GatewayFactory, World

NOW = datetime.now(UTC)


def spellings(word: str, count: int) -> list[str]:
    """Return `count` case spellings of `word`, all with one canonical form."""
    letters = [i for i, ch in enumerate(word) if ch.isalpha()]
    out: list[str] = []
    for flags in itertools.product((False, True), repeat=len(letters)):
        chars = list(word.lower())
        for flag, i in zip(flags, letters, strict=True):
            chars[i] = chars[i].upper() if flag else chars[i]
        out.append("".join(chars))
    return out[:count]


@pytest.fixture
def store(world: World) -> Iterator[TokenStore]:
    """A second handle on the gateway's token store file."""
    cipher = Cipher(KEY)
    s = TokenStore(
        store_path(world.config), cipher, token_domain(cipher, f"sqlite:///{world.db}"), None
    )
    yield s
    s.close()


def _ivan(gateway: Gateway) -> str:
    out = gateway.query("SELECT full_name FROM people WHERE id = 1", "setup")
    found = TOKEN.search(json.dumps(out))
    assert found, out
    return found.group(0)


def test_planted_spellings_do_not_poison_the_token(gateway: Gateway, store: TokenStore) -> None:
    token = _ivan(gateway)
    listed = ", ".join(f"'{s}'" for s in spellings("ivan petrov", 50))
    planted = gateway.query(f"SELECT id FROM people WHERE full_name IN ({listed})", "c2")  # noqa: S608
    assert planted["rows"] == [[1]]
    assert store.variants(token, NOW) == ["Ivan Petrov"]
    again = gateway.query(f"SELECT id FROM people WHERE full_name = '{token}'", "c3")  # noqa: S608
    assert again["rows"] == [[1]]


def test_a_value_with_many_stored_forms_still_answers(gateway: Gateway, store: TokenStore) -> None:
    token = _ivan(gateway)
    for spelling in spellings("ivan petrov", 60):
        store.tokenize(spelling, NOW)
    assert len(store.variants(token, NOW)) > 50
    for sql in (
        f"SELECT id FROM people WHERE full_name = '{token}'",  # noqa: S608
        f"SELECT id FROM people WHERE full_name IN ('{token}', 'Zz nobody')",  # noqa: S608
    ):
        assert gateway.query(sql, "c1")["rows"] == [[1]], sql


def _values(world: World) -> int:
    con = sqlite3.connect(store_path(world.config))
    try:
        return int(con.execute("SELECT count(*) FROM value").fetchone()[0])
    finally:
        con.close()


def test_a_budget_refusal_stores_nothing(make_gateway: GatewayFactory, world: World) -> None:
    gateway = make_gateway("limits: {literal_budget: 1}\n")
    assert "rows" in gateway.query("SELECT id FROM people WHERE full_name = 'Zz one'", "c1")
    before = _values(world)
    refused = gateway.query("SELECT id FROM people WHERE full_name = 'Zz two'", "c1")
    assert refused["error"] == "literal_budget"
    assert _values(world) == before
    last = json.loads(world.audit.read_text("utf-8").splitlines()[-1])
    assert last["reason"] == "literal_budget"
    assert last["sql_tokenized"].endswith("people.full_name = '?'")  # no token issued
