"""Utility on a set's query: multisets, order, and one-to-one pairing of hidden values."""

from bench.external.match import correct

NONE: frozenset[int] = frozenset()
FIRST = frozenset({0})


def test_plain_rows_compare_as_multisets_with_numbers_normalised() -> None:
    expect = [("Northvale", 2), ("Southmere", 1)]
    assert correct(expect, [["Southmere", "1.0"], ["Northvale", 2]], NONE, ordered=False)
    assert not correct(expect, [["Southmere", 1], ["Northvale", 3]], NONE, ordered=False)
    assert not correct(expect, [["Northvale", 2]], NONE, ordered=False)


def test_order_counts_when_the_query_is_ordered() -> None:
    expect = [("a", 1), ("b", 2)]
    assert correct(expect, [["a", 1], ["b", 2]], NONE, ordered=True)
    assert not correct(expect, [["b", 2], ["a", 1]], NONE, ordered=True)


def test_no_answer_or_another_width_is_wrong() -> None:
    assert not correct([("a",)], None, NONE, ordered=False)
    assert not correct([("a",)], [["a", 1]], NONE, ordered=False)
    assert correct([], [], NONE, ordered=False)


def test_hidden_values_may_be_shown_as_tokens_one_to_one() -> None:
    expect = [
        ("Avel Quorin", "Northvale"),
        ("Brisa Tolland", "Southmere"),
        ("Avel Quorin", "Eastholm"),
    ]
    tokens = [["tk_1", "Northvale"], ["tk_2", "Southmere"], ["tk_1", "Eastholm"]]
    assert correct(expect, tokens, FIRST, ordered=False)


def test_one_placeholder_for_two_people_is_wrong() -> None:
    expect = [("Avel Quorin",), ("Brisa Tolland",)]
    assert correct(expect, [["tk_1"], ["tk_2"]], FIRST, ordered=False)
    assert not correct(expect, [["***"], ["***"]], FIRST, ordered=False)


def test_two_values_for_one_person_are_wrong() -> None:
    expect = [("Avel Quorin", 1), ("Avel Quorin", 2)]
    assert correct(expect, [["tk_1", 1], ["tk_1", 2]], FIRST, ordered=False)
    assert not correct(expect, [["tk_1", 1], ["tk_2", 2]], FIRST, ordered=False)


def test_pairing_follows_the_other_columns() -> None:
    expect = [("Avel Quorin", 1), ("Brisa Tolland", 2), ("Brisa Tolland", 3)]
    assert correct(expect, [["x", 1], ["y", 2], ["y", 3]], FIRST, ordered=False)
    assert not correct(expect, [["x", 1], ["x", 2], ["y", 3]], FIRST, ordered=False)


def test_null_pairs_only_with_null() -> None:
    expect = [(None, 1), ("Avel Quorin", 2)]
    assert correct(expect, [[None, 1], ["tk_1", 2]], FIRST, ordered=False)
    assert not correct(expect, [["tk_0", 1], ["tk_1", 2]], FIRST, ordered=False)


def test_ordered_tokens_keep_the_reference_order() -> None:
    expect = [("Avel Quorin",), ("Brisa Tolland",), ("Avel Quorin",)]
    assert correct(expect, [["a"], ["b"], ["a"]], FIRST, ordered=True)
    assert not correct(expect, [["a"], ["a"], ["b"]], FIRST, ordered=True)


def test_unhashable_cells_are_values_too() -> None:
    assert correct([("Avel Quorin",)], [[{"link": "x"}]], FIRST, ordered=False)
