"""The mask domain: its own tokens, never bound as an identifier's."""

from datetime import datetime

import pytest

from incognito_sql.core.tokens.store import InvalidToken, TokenStore


def test_masks_get_their_own_token_for_the_same_value(store: TokenStore, now: datetime) -> None:
    masks = store.masks()
    mask = masks.tokenize("ivan@example.com", now)
    ident = store.tokenize("ivan@example.com", now)
    assert mask != ident
    assert masks.reveal(mask) == "ivan@example.com"
    assert masks.tokenize("ivan@example.com", now) == mask


def test_a_mask_token_is_unknown_to_the_identifier_domain(store: TokenStore, now: datetime) -> None:
    mask = store.masks().tokenize("ivan@example.com", now)
    with pytest.raises(InvalidToken):
        store.variants(mask, now)
    with pytest.raises(InvalidToken):
        store.reveal(mask)
    ident = store.tokenize("ivan@example.com", now)
    with pytest.raises(InvalidToken):
        store.masks().reveal(ident)
