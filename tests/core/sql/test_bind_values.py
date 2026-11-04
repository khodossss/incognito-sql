"""Python values of literal numbers, and raw forms coerced to a column's family."""

from decimal import Decimal

import pytest
from sqlglot import exp

from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.bind_values import coerce_raws, literal_value


@pytest.mark.parametrize(
    ("lit", "value"),
    [
        (exp.Literal(this="15", is_string=False), 15),
        (exp.Literal(this="1.0", is_string=False), Decimal("1.0")),
        (exp.Literal.string("15"), "15"),
    ],
)
def test_literal_value(lit: exp.Literal, value: object) -> None:
    found = literal_value(lit)
    assert found == value
    assert type(found) is type(value)


@pytest.mark.parametrize("text", ["NaN", "Infinity", "1.2.3"])
def test_number_that_is_no_finite_value_is_refused(text: str) -> None:
    with pytest.raises(Rejection) as raised:
        literal_value(exp.Literal(this=text, is_string=False))
    assert raised.value.reason is Reason.NODE_NOT_ALLOWED


@pytest.mark.parametrize(
    ("raws", "column_type", "expected"),
    [
        (["7", "7.0", "7.5", "x"], "INTEGER", [7]),
        (["1.5", "NaN", "1.50", "x"], "NUMERIC(10, 2)", [Decimal("1.5")]),
        (["Zq", "Zq", "7"], "TEXT", ["Zq", "7"]),
    ],
)
def test_raw_forms_are_coerced_to_the_family(
    raws: list[str], column_type: str, expected: list[object]
) -> None:
    assert coerce_raws(raws, column_type) == expected


@pytest.mark.parametrize(("raw", "column_type"), [("7.5", "INTEGER"), ("NaN", "NUMERIC")])
def test_no_form_of_the_family_left_is_refused(raw: str, column_type: str) -> None:
    with pytest.raises(Rejection) as raised:
        coerce_raws([raw], column_type)
    assert raised.value.reason is Reason.LITERAL_TYPE_MISMATCH
