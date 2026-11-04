"""Under strict a number prints one way whatever its type: no spelling tells the scan order."""

import random
from datetime import datetime
from decimal import Decimal

import pytest

from incognito_sql.core.config import Declaration
from incognito_sql.core.output.mask import spelled_once
from incognito_sql.core.output.shape import shape
from incognito_sql.core.tokens.store import TokenStore

from .conftest import OPEN, out_rows, rows


@pytest.mark.parametrize(
    ("value", "printed"),
    [
        (1.0, 1),
        (1, 1),
        (Decimal("1.0"), 1),
        (Decimal("1.50"), Decimal("1.5")),
        (2.5, 2.5),
        (2.0**60, 2.0**60),  # past the integers a float holds exactly
        (Decimal("1E+19"), 10**19),
        (Decimal("1E+40"), Decimal("1E+40")),  # past the digits an answer prints
        ("1.0", "1.0"),
        (True, True),
        (None, None),
    ],
)
def test_a_number_prints_one_way(value: object, printed: object) -> None:
    assert spelled_once(value) == printed
    assert type(spelled_once(value)) is type(printed)


def test_strict_prints_equal_numbers_alike(
    store: TokenStore, decl: Declaration, now: datetime
) -> None:
    values = [(1,), (1.0,), (Decimal("1.00"),), (1.0000000000001,)]

    def printed(profile: str) -> list[object]:
        d = decl.model_copy(update={"protection": profile})
        out = shape(rows(values), [OPEN], store, d, now, random.Random(0), keep_order=True)  # noqa: S311
        return [row[0] for row in out_rows(out)]

    assert printed("strict") == [1, 1, 1, 1]
    assert printed("balanced") == [1, 1.0, "1.00", 1.0]
