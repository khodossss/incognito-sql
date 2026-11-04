"""Computed numbers: floats rounded to 12 digits, masked by the size of their integer part."""

import random
from datetime import datetime
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from incognito_sql.core.config import Declaration
from incognito_sql.core.output.detect import looks_personal
from incognito_sql.core.output.mask import MASK
from incognito_sql.core.output.shape import shape
from incognito_sql.core.tokens.store import TokenStore

from .conftest import OPEN, out_rows, rows


def _cell(store: TokenStore, decl: Declaration, now: datetime, value: object) -> object:
    out = shape(rows([(value,)]), [OPEN], store, decl, now, random.Random(0))  # noqa: S311
    return out_rows(out)[0][0]


@pytest.mark.parametrize(
    "value",
    [
        972501110001.0,
        4.111111111111111e15,
        4.111111111111111e17,
        1e16,
        -972501110001.0,
        Decimal("972501110001.00"),
        Decimal("1E+20"),
        972501110001,
    ],
)
def test_identifier_sized_numbers_are_masked(
    store: TokenStore, decl: Declaration, now: datetime, value: object
) -> None:
    assert looks_personal(value)
    assert _cell(store, decl, now, value) == MASK


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (355.59999999999997, 355.6),
        (3.6666666666666665, 3.66666666667),
        (118.33333333333333, 118.333333333),
        (999999999.5, 999999999.5),
        (Decimal("118.3333333333333333"), "118.3333333333333333"),
        (Decimal("355.6000000000000000"), "355.6000000000000000"),
        (123456789, 123456789),
    ],
)
def test_computed_numbers_are_shown(
    store: TokenStore, decl: Declaration, now: datetime, value: object, shown: object
) -> None:
    assert _cell(store, decl, now, value) == shown


@settings(
    max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(st.integers(0, 100_000), max_size=10_000), st.randoms())
def test_summation_order_does_not_change_the_output(
    store: TokenStore, decl: Declaration, now: datetime, cents: list[int], order: random.Random
) -> None:
    values = [c / 100 for c in cents]
    shuffled = list(values)
    order.shuffle(shuffled)
    outputs = {_cell(store, decl, now, sum(v)) for v in (values, values[::-1], shuffled)}
    assert outputs == {float(Decimal(sum(cents)) / 100)}
