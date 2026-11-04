"""The exact type a bind compared with an identifier is cast to, and the values it holds."""

import re
from datetime import datetime
from decimal import Decimal
from functools import cache

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.bind_domain import Decimals, Domain, Floats, Integers, Money
from incognito_sql.core.sql.bind_forms import Booleans, Dates, Nothing, Stamps, Texts, Uuids
from incognito_sql.core.sql.typefamily import (
    DECIMAL_TYPES,
    INTEGER_TYPES,
    base_type,
    cast_group,
    is_composite,
)

T = exp.DataType.Type
_NO_CAST = frozenset({"integer", "character"})
# Enumerated, set and domain types: no literal or token is compared with them.
_ENUMERATED = frozenset({"ENUM", "SET", "DOMAIN"})
_REFUSED = frozenset({T.NULL, T.UNKNOWN, T.USERDEFINED, T.ENUM, T.ENUM8, T.ENUM16, T.SET})
# Spellings sqlglot reads as a wider type: T-SQL REAL is FLOAT(24), not FLOAT.
_SPELLED = {("tsql", "REAL"): "FLOAT(24)"}
# Every target MySQL's CAST takes, written in full.
_MYSQL_CAST = re.compile(
    r"UNSIGNED|SIGNED|DECIMAL(\(\d+(, \d+)?\))?|DOUBLE|FLOAT(\(\d+\))?|REAL|DATE|YEAR|JSON"
    r"|(DATETIME|TIME)(\(\d\))?|(CHAR|NCHAR|BINARY)(\(\d+\))?"
)
INT64 = Integers(-(1 << 63), 1 << 63)
SINGLE = Floats(Decimal("1.1754943508222875e-38"), Decimal("3.4028234663852886e38"))
DOUBLE = Floats(Decimal("2.2250738585072014e-308"), Decimal("1.7976931348623157e308"))
# Unparameterized DECIMAL: Postgres NUMERIC's own limits; elsewhere the dialect's default.
_DECIMAL = {"postgres": Decimals(131072 + 16383, 16383, pad=False), "mysql": Decimals(10, 0)}
_DECIMAL |= {"tsql": Decimals(18, 0)}
_MONEY = {
    ("postgres", T.MONEY): Money(
        Decimals(19, 2),
        Decimal("-92233720368547758.08"),
        Decimal("92233720368547758.07"),
        dollars=True,
    ),
    ("tsql", T.MONEY): Money(
        Decimals(19, 4), Decimal("-922337203685477.5808"), Decimal("922337203685477.5807")
    ),
    ("tsql", T.SMALLMONEY): Money(Decimals(10, 4), Decimal("-214748.3648"), Decimal("214748.3647")),
}
# T-SQL DATETIME: from 1753, in 1/300 s, read from a string only with a T and 3 decimals.
_LEGACY = Stamps(zone=False, first=datetime(1753, 1, 1), millis=True)  # noqa: DTZ001
_NAIVE = frozenset({T.TIMESTAMP, T.TIMESTAMPNTZ, T.DATETIME, T.DATETIME2})
_UNSIGNED_BITS = {T.UTINYINT: 8, T.USMALLINT: 16, T.UMEDIUMINT: 24, T.UINT: 32}
_UNSIGNED_BITS |= {T.UBIGINT: 64, T.UINT128: 128, T.UINT256: 256}
_SIMPLE: dict[object, Domain] = {T.DATE: Dates(), T.UUID: Uuids()}
_SIMPLE |= {kind: Integers(0, 1 << bits) for kind, bits in _UNSIGNED_BITS.items()}
_SIMPLE |= {T.INT128: Integers(-(1 << 127), 1 << 127), T.INT256: Integers(-(1 << 255), 1 << 255)}
_SIMPLE |= {T.BOOLEAN: Booleans(), T.TIMESTAMPTZ: Stamps(zone=True), T.DOUBLE: DOUBLE}


def bind_cast(column_type: str, dialect: str) -> exp.DataType | None:
    """Return the type to cast a bind compared with a column of `column_type` to.

    None: no cast is needed (a signed integer of at most 64 bits, a character
    type, or SQLite, which converts a bind by the column's affinity, never the
    column). Raises Rejection(LITERAL_TYPE_MISMATCH) for an enumerated, set or
    domain type, and when the dialect cannot write the column's exact type in a CAST.
    """
    if base_type(column_type) in _ENUMERATED:
        raise Rejection(Reason.LITERAL_TYPE_MISMATCH)
    if dialect == "sqlite" or cast_group(column_type) in _NO_CAST:
        return None
    target = _target(column_type, dialect)
    if target is None:
        raise Rejection(Reason.LITERAL_TYPE_MISMATCH)
    return target.copy()


# Strict token forms: a raw form outside the column's exact type is dropped.
def bind_domain(column_type: str, dialect: str) -> Domain:
    """Return the check of values compared with a column of `column_type`.

    Raises Rejection(LITERAL_TYPE_MISMATCH) where `bind_cast` does.
    """
    target = bind_cast(column_type, dialect)
    if target is not None:
        return _domain(target, dialect)
    base = base_type(column_type)
    if dialect == "sqlite":  # by affinity; sqlite3 binds at most a signed 64-bit integer
        return INT64 if base in INTEGER_TYPES else DOUBLE if base in DECIMAL_TYPES else Texts()
    return INT64 if cast_group(column_type) == "integer" else Texts(no_nul=dialect == "postgres")


def _domain(target: exp.DataType, dialect: str) -> Domain:
    kind = target.this
    params = [int(p.name) for p in target.expressions if isinstance(p, exp.DataTypeParam)]
    if kind is T.DECIMAL:
        if not params:  # DuckDB builds a bare DECIMAL as (18, 3); SQLite casts nothing
            return _DECIMAL[dialect]
        return Decimals(params[0], params[1] if len(params) > 1 else 0)
    if kind is T.FLOAT:  # FLOAT(p > 24) and T-SQL's bare FLOAT are double precision
        wide = params[0] > 24 if params else dialect == "tsql"  # noqa: PLR2004
        return DOUBLE if wide else SINGLE
    if kind in _NAIVE:
        return _LEGACY if dialect == "tsql" and kind is T.DATETIME else Stamps(zone=False)
    return _MONEY.get((dialect, kind)) or _SIMPLE.get(kind, Nothing())


@cache
def _target(column_type: str, dialect: str) -> exp.DataType | None:
    if not column_type or is_composite(column_type):
        return None
    spelled = _SPELLED.get((dialect, base_type(column_type)), column_type)
    try:
        target = exp.DataType.build(spelled, dialect=dialect)
        sql = exp.Cast(this=exp.column("x"), to=target.copy()).sql(dialect=dialect)
        back = sqlglot.parse_one(sql, read=dialect)
    except SqlglotError:
        return None
    # An unsigned float or decimal: no CAST keeps the sign rule.
    unsigned = "UNSIGNED" in column_type.upper().split() and target.this not in _UNSIGNED_BITS
    if not isinstance(target.this, T) or target.this in _REFUSED or unsigned:
        return None
    if not isinstance(back, exp.Cast) or back.to != target:
        return None  # the dialect writes a different type, or a function
    if dialect == "mysql" and not _MYSQL_CAST.fullmatch(sql.removeprefix("CAST(x AS ")[:-1]):
        return None
    return target
