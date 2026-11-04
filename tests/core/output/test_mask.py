"""The masker: plain text or a link, verified columns skipped, the kind remembered."""

from datetime import date
from decimal import Decimal

import pytest

from incognito_sql.core.output.detect import personal_kind
from incognito_sql.core.output.mask import MASK, Masker


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("write to ivan@example.com", "email"),
        ("4111 1111 1111 1111", "card"),
        ("+972 50 123 4567", "phone"),
        ("GB82 WEST 1234 5698 7654 32", "iban"),
        ("ghp_" + "a1" * 12, "secret"),
        (1234567890, "number"),
        (Decimal("-9876543210.5"), "number"),
        (["ok", ["x", "ivan@example.com"]], "email"),
        ("plain words", None),
        (123456789, None),
        (None, None),
    ],
)
def test_personal_kind_names_the_category(value: object, kind: str | None) -> None:
    assert personal_kind(value) == kind


def test_nesting_past_the_limit_is_its_own_kind() -> None:
    deep: object = "ok"
    for _ in range(9):
        deep = [deep]
    assert personal_kind(deep) == "nested"


def test_without_a_link_the_mask_is_text_and_the_kind_is_kept() -> None:
    masker = Masker()
    assert masker.cell(0, "ok") == "ok"
    assert masker.cell(1, "ivan@example.com") == MASK
    assert masker.cell(1, "+972 50 123 4567") == MASK
    assert masker.found == {1: "email"}  # the first kind seen in a column stays


def test_a_link_replaces_the_value_and_gets_the_value() -> None:
    seen: list[object] = []

    def link(value: object) -> str:
        seen.append(value)
        return "http://127.0.0.1:1/m/tk_x"

    masker = Masker(link)
    assert masker.cell(0, 12345678901) == "http://127.0.0.1:1/m/tk_x"
    assert seen == [12345678901]


def test_checked_columns_and_dates_pass_unexamined() -> None:
    masker = Masker(checked=frozenset({0}))
    assert masker.cell(0, "ivan@example.com") == "ivan@example.com"
    assert masker.cell(1, date(2026, 1, 2)) == "2026-01-02"
    assert masker.cell(1, b"x") == "\u2039bytes\u203a"
    assert masker.found == {}


def test_floats_are_rounded_before_the_check() -> None:
    assert Masker().cell(0, 0.1 + 0.2) == 0.3
