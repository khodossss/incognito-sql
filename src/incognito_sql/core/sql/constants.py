"""Constants the server can tell never fail: small numbers, their arithmetic, a text cast."""

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlglot import exp

from incognito_sql.core.sql.typefamily import TEXT, base_type, literal_kind

# Inside the narrowest integer every DBMS gives a plain literal: every step of the arithmetic too.
_LIMIT = Decimal(2) ** 31
_ARITHMETIC = (exp.Add, exp.Sub, exp.Mul, exp.Div)


def safe_constant(node: exp.Expr) -> bool:
    """Tell whether a constant expression evaluates without error.

    A number, a sign, `+ - * /` over numbers whose every step stays inside 32 bits with
    no division by zero, a cast of a literal to text, and a strict `YYYY-MM-DD` cast to
    DATE. Any other cast, function or larger number may fail.
    """
    if isinstance(node, exp.Cast):
        return _fitting_cast(node)
    try:
        _number(node)
    except (ArithmeticError, ValueError, InvalidOperation):
        return False
    return True


def _number(node: exp.Expr) -> Decimal:
    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, exp.Literal) and not node.is_string:
        value = Decimal(node.name)
    elif isinstance(node, exp.Neg):
        value = -_number(node.this)
    elif isinstance(node, _ARITHMETIC):
        left, right = _number(node.this), _number(node.expression)
        if isinstance(node, exp.Div):
            value = left / right  # a zero divisor raises
        elif isinstance(node, exp.Mul):
            value = left * right
        else:
            value = left + right if isinstance(node, exp.Add) else left - right
    else:
        msg = "not a plain number"
        raise ValueError(msg)
    if not value.is_finite() or abs(value) >= _LIMIT:
        msg = "past 32 bits"
        raise ArithmeticError(msg)
    return value


def _fitting_cast(cast: exp.Cast) -> bool:
    value = cast.this
    target = cast.to.sql()
    if not isinstance(value, exp.Literal):
        return False
    if literal_kind(target) == TEXT:
        return True
    if base_type(target) == "DATE" and value.is_string:
        try:
            return date.fromisoformat(value.name).isoformat() == value.name
        except ValueError:
            return False
    return False
