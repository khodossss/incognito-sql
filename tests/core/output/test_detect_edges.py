"""Detection at its edges: length and digit bounds, Luhn arithmetic, scan budgets, nesting."""

from decimal import Decimal

import pytest

from incognito_sql.core.output.detect import looks_personal

EDGE_POSITIVE = [
    "x@example.com",
    "ivan@x.io",
    "price @ 5, mail ivan@example.com",
    "ivan@example.com, cc @",
    "@team ivan@example.com",
    "card 4222 2222 2222 2 ok",
    "card 6304 0000 0000 0000 018 ok",
    "pay 5105 1051 0510 5100 now",
    "NO93 8601 1117 947",
    "DE89 3704 0044 0532 0130 00 EUR",
    "123-4567",
    "050.123.4567",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIx.abcdef",
    "0123456789ghijkl" * 3,
    1_000_000_000,
    Decimal("1E+400"),
]

EDGE_NEGATIVE = [
    "a@ " * 50,
    "pay 5105 1051 0510 5101 now",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIx.abcde",
    "TheQuickBrownFoxJumpsOverTheLazyDogAgainAndAgain",
    999_999_999,
]


@pytest.mark.parametrize("value", EDGE_POSITIVE)
def test_edge_values_match(value: object) -> None:
    assert looks_personal(value)


@pytest.mark.parametrize("value", EDGE_NEGATIVE)
def test_edge_values_do_not_match(value: object) -> None:
    assert not looks_personal(value)


def _after_decoys(decoy: str, count: int, real: str) -> str:
    return "x " + f"{decoy}, " * count + real


@pytest.mark.parametrize(
    ("decoy", "real"),
    [
        ("1111 1111 1111 1111", "4111 1111 1111 1111"),
        ("GB82 WEST 1234 5698 7654 33", "GB82 WEST 1234 5698 7654 32"),
    ],
)
def test_candidates_beyond_the_scan_budget_hide_the_cell(decoy: str, real: str) -> None:
    # Fifty candidates are examined; a cell with more is masked, not passed unexamined.
    assert looks_personal(_after_decoys(decoy, 49, real))
    assert not looks_personal(_after_decoys(decoy, 49, decoy))
    assert looks_personal(_after_decoys(decoy, 50, decoy))


def test_ats_beyond_the_scan_budget_hide_the_cell() -> None:
    assert not looks_personal("a@ " * 50)
    assert looks_personal("a@ " * 51)


def _nested(levels: int) -> object:
    value: object = "Haifa"
    for _ in range(levels):
        value = [value]
    return value


def test_nesting_beyond_eight_levels_is_treated_as_personal() -> None:
    assert not looks_personal(_nested(8))
    assert looks_personal(_nested(9))
