"""Spellings come only from database output; a model's literal gets a token, no spelling."""

from datetime import datetime

from incognito_sql.core.tokens.store import TokenStore


def test_token_for_keeps_no_spelling(store: TokenStore, now: datetime) -> None:
    token = store.token_for("IVAN Petrov", now)
    assert store.variants(token, now) == []
    assert store.variants_for_literal("Zz other") == ["Zz other"]
    assert store.variants_for_literal("ivan petrov") == ["ivan petrov"]


def test_token_for_and_tokenize_share_the_token(store: TokenStore, now: datetime) -> None:
    token = store.token_for("IVAN Petrov", now)
    assert store.tokenize("Ivan Petrov", now) == token
    assert store.token_for("ivan  petrov", now) == token
    assert store.variants(token, now) == ["Ivan Petrov"]


def test_reveal_falls_back_to_the_canonical_form(store: TokenStore, now: datetime) -> None:
    token = store.token_for("  IVAN   Petrov ", now)
    assert store.reveal(token) == "ivan petrov"
    store.tokenize("Ivan Petrov", now)
    assert store.reveal(token) == "Ivan Petrov"
