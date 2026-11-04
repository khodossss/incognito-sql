"""The L2 oracle on real data: pieces of hidden values, and what is visible anyway."""

import json
import random
import tracemalloc
from collections.abc import Iterator

from incognito_sql.levels.fragment import Fragments, Run, needed
from incognito_sql.levels.partial import Pieces, Visible, shown_in_part

EMAIL = "avel.quorin@example.test"  # invented
HIDDEN = [  # invented
    EMAIL,
    "Brisa Tolland",
    "acct 0042117789 west",
    "the northvale ferry leaves at dawn and returns before the evening tide",
]


def test_a_fragment_needs_six_characters_or_half_the_value() -> None:
    assert [needed(n) for n in (8, 12, 13, 24)] == [6, 6, 7, 12]


def test_a_long_enough_piece_is_found_a_shorter_one_is_not() -> None:
    fragments = Fragments([EMAIL])
    assert [r.piece for r in fragments.found("Mail: AVEL.QUORIN@ex***")] == ["avel.quorin@ex"]
    assert fragments.found("quorin@exam") == []  # 11 of the 12 a 24-character value needs


def test_values_too_short_or_without_letters_are_not_looked_for() -> None:
    fragments = Fragments(["Brisa T", "--------", b"corwin.ashe"])
    assert fragments.size == 1
    assert [r.value for r in fragments.found("x corwin.as y")] == ["corwin.ashe"]


def test_a_long_value_is_found_by_its_sampled_grams() -> None:
    post = "the northvale ferry leaves at dawn and returns before the evening tide"
    piece = post[10:50]
    assert [r.piece for r in Fragments([post]).found(f"<< {piece} >>")] == [piece]


def test_a_run_yields_its_windows() -> None:
    assert list(Run("abcdefgh", "abcdefg").windows()) == ["abcdef", "bcdefg"]


def test_a_piece_visible_anyway_or_shown_whole_is_not_counted() -> None:
    fragments = Fragments([EMAIL, "brisa.tolland@example.test"])
    text = "avel.quorin@ex, brisa.tolland@example.test"
    runs = fragments.found(text)
    whole = ["brisa.tolland@example.test"]
    assert shown_in_part(runs, whole, ()) == {EMAIL}
    assert shown_in_part(runs, whole, (Visible(["AVEL.QUORIN@EXAMPLE"]),)) == set()
    assert shown_in_part(runs, whole, (Visible(["avel.quorin@e"]),)) == {EMAIL}  # a window left
    assert 3 not in Visible(["3"])


def test_a_piece_of_digits_only_needs_eight() -> None:
    assert list(Run("user000001", "000001").windows()) == []  # six digits match any number
    assert list(Run("7182887233", "7182887").windows()) == []
    assert list(Run("7182887233", "71828872").windows()) == ["71828872"]
    assert list(Run("+7182887233", "+718288").windows()) == ["+71828"]  # not digits only


def _shown(rng: random.Random, count: int) -> Iterator[str]:
    """Yield invented texts holding slices of the hidden values in their compared forms."""
    letters = "abcdefghijklmnopqrstuvwxyz0123456789 .@"
    for _ in range(count):
        value = rng.choice(HIDDEN)
        start = rng.randrange(len(value))
        piece = value[start : start + rng.randrange(3, 30)]
        piece = piece.upper() if rng.random() < 0.3 else piece
        noise = "".join(rng.choices(letters, k=rng.randrange(0, 12)))
        text = f"{noise}{piece}{noise[::-1]}"
        yield json.dumps(text) if rng.random() < 0.2 else text


def test_pieces_answer_every_window_as_the_texts_themselves_do() -> None:
    fragments = Fragments(HIDDEN)
    texts = list(_shown(random.Random(7), 400))  # noqa: S311 -- reproducible
    pieces, visible = Pieces(fragments, texts), Visible(texts)
    windows = {w for v in HIDDEN for w in Run(v.casefold(), v.casefold()).windows()}
    assert {w for w in windows if w in pieces} == {w for w in windows if w in visible}
    assert any(w in pieces for w in windows)
    assert not all(w in pieces for w in windows)


def test_pieces_do_not_keep_the_texts() -> None:
    fragments = Fragments(HIDDEN)
    tracemalloc.start()
    try:
        texts = _shown(random.Random(3), 300)  # noqa: S311 -- reproducible
        pieces = Pieces(fragments, (t * 40 for t in texts))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1 << 16  # the texts are about 300 kB; joined, as Visible does, twice that
    assert any(w in pieces for v in HIDDEN for w in Run(v.casefold(), v.casefold()).windows())
