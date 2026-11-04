"""The oracle on real data: hidden values found whole, visible ones and noise left out."""

import pytest

from incognito_sql.levels.oracle import Oracle, forms, number, plain, variants

HIDDEN = ["Avel Quorin", "avel.quorin@example.test", 5550001234, 120.5, 80.0, "Ash"]


@pytest.fixture
def oracle() -> Oracle:
    return Oracle(HIDDEN)


def test_plain_and_number_forms() -> None:
    assert plain("  Avel\n  QUORIN ") == "avel quorin"
    assert number("1234.50") == "1234.5"
    assert number("1.2e3") == "1200"
    assert number("-0.0") == "0"
    assert number("abc") is None
    assert number("NaN") is None
    assert number("1e999999999") is None
    assert forms(80.0) == {"80.0"}  # the plain form "80" is under four characters
    assert forms(b"Zed Ommar") == {"zed ommar"}
    assert forms("Ash") == set()


@pytest.mark.parametrize(
    "text",
    [
        '{"rows": [["Avel Quorin"]]}',
        "name: AVEL   quorin, age 41",
        '"avel.quorin@example.test"',
        "phone 5550001234",
        "phone 5.550001234e9",
        "total 120.50",
        "total 80.0",
        '"Avel Quorin"'.replace("Avel", "\\u0041vel"),
    ],
)
def test_finds_a_hidden_value_whole(oracle: Oracle, text: str) -> None:
    assert oracle.found(text)


@pytest.mark.parametrize(
    "text",
    [
        "Avel Quorinson",  # part of a longer word
        "xavel quorin",
        "55500012345",  # part of a longer number
        "1120.5",
        "120.55",
        "12.80.0",
        "Ash and Asher",  # shorter than four characters: noise
        "",
    ],
)
def test_misses_parts_and_noise(oracle: Oracle, text: str) -> None:
    assert oracle.found(text) == []


def test_drop_forgets_values_seen_elsewhere(oracle: Oracle) -> None:
    before = oracle.size
    assert oracle.drop(["a city named Avel Quorin", "nothing"]) == 1
    assert oracle.size == before - 1
    assert oracle.found("Avel Quorin") == []
    assert oracle.found("phone 5550001234") == ["5550001234"]


def test_a_long_text_is_found_whole_only() -> None:
    body = "<p>I " + "keep a ledger of every invented harbour " * 20 + "here.</p>"
    oracle = Oracle([body])
    assert oracle.found(f'{{"body": "{body.upper()}"}}') == [" ".join(body.casefold().split())]
    assert oracle.found(body[:-5]) == []


def test_many_values_sharing_a_word_are_told_apart() -> None:
    oracle = Oracle([f"Quorinhall {i} Lane" for i in range(3000)] + ["Quorinhall"])
    text = " ".join(f"Quorinhall {i} Road" for i in range(3000)) + " Quorinhall 17 Lane"
    assert set(oracle.found(text)) == {"quorinhall 17 lane", "quorinhall"}


def test_values_without_letters_or_digits_are_not_looked_for() -> None:
    assert Oracle(["----", "...."]).size == 0


def test_variants_decode_json_escapes() -> None:
    assert "line one line two" in variants("line one\\nline two")
