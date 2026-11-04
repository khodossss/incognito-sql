"""Rows keep the order the query asked for; without ORDER BY they are shuffled."""

import random
from datetime import datetime

from incognito_sql.core.config import Declaration
from incognito_sql.core.output.shape import shape
from incognito_sql.core.tokens.store import TokenStore

from .conftest import OPEN, out_rows, rows

DATA = [(i,) for i in range(20)]


def test_kept_order_is_the_database_order(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    out = shape(rows(DATA), [OPEN], store, decl, now, rng, keep_order=True)
    assert out_rows(out) == [[i] for i in range(20)]


def test_rows_are_shuffled_by_default(
    store: TokenStore, decl: Declaration, now: datetime, rng: random.Random
) -> None:
    out = shape(rows(DATA), [OPEN], store, decl, now, rng)
    assert sorted(out_rows(out)) == [[i] for i in range(20)]
    assert out_rows(out) != [[i] for i in range(20)]
