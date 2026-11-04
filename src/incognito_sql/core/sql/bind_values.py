"""Python values for bind parameters: literal numbers and raw forms coerced to a column."""

from decimal import Decimal, InvalidOperation

from sqlglot import exp

from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.typefamily import DECIMAL_TYPES, INTEGER_TYPES, base_type


def coerce_raws(raws: list[str], column_type: str) -> list[object]:
    """Coerce raw forms to the column's family, de-duplicated, in order.

    Text and unknown types keep the strings. For an integer or decimal column a
    raw form that does not parse is dropped; none left -> LITERAL_TYPE_MISMATCH.
    """
    base = base_type(column_type)
    if base not in INTEGER_TYPES | DECIMAL_TYPES:
        return list(dict.fromkeys(raws))
    coerced = [_coerce(raw, integer=base in INTEGER_TYPES) for raw in raws]
    found = [v for v in coerced if v is not None]
    if not found:
        raise Rejection(Reason.LITERAL_TYPE_MISMATCH)
    return list(dict.fromkeys(found))


def literal_value(lit: exp.Literal) -> str | int | Decimal:
    """Return the Python value of a literal; `1.0` stays a Decimal, so `1.0 / 3` is not integer."""
    if lit.is_string:
        return str(lit.this)
    if lit.this.isdigit():
        return int(lit.this)
    value = _decimal(lit.this)
    if value is None:
        raise Rejection(Reason.NODE_NOT_ALLOWED)
    return value


def _decimal(text: str) -> Decimal | None:
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _coerce(raw: str, *, integer: bool) -> int | Decimal | None:
    value = _decimal(raw)
    if value is None or not integer:
        return value
    return int(value) if value == value.to_integral_value() else None
