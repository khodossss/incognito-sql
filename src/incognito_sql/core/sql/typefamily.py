"""SQL column types: the kind of literal a column takes, and its cast-safe group."""

import re

# Literal kinds and bind coercion: a value of our own is bound to its column's type.
INTEGER_TYPES = frozenset(
    {"INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT", "MEDIUMINT", "INT1", "INT2", "INT4"}
    | {"INT8", "INT16", "INT32", "INT64", "INT128", "HUGEINT", "UHUGEINT", "UBIGINT", "UINTEGER"}
    | {"USMALLINT", "UTINYINT", "UINT", "LONG", "SHORT", "SIGNED", "SERIAL", "BIGSERIAL"}
    | {"SMALLSERIAL", "SERIAL2", "SERIAL4", "SERIAL8"}
)
DECIMAL_TYPES = frozenset(
    {"NUMERIC", "DECIMAL", "DEC", "FIXED", "NUMBER", "REAL", "FLOAT", "FLOAT4", "FLOAT8", "DOUBLE"}
)
TEXT_TYPES = frozenset(
    {"TEXT", "VARCHAR", "CHAR", "CHARACTER", "NCHAR", "NVARCHAR", "VARCHAR2", "NVARCHAR2"}
    | {"CLOB", "NCLOB", "STRING", "CITEXT", "NTEXT", "TINYTEXT", "MEDIUMTEXT", "LONGTEXT"}
    | {"BPCHAR", "NATIONAL"}
)
NUMBER = "number"
TEXT = "text"

# Identifier against identifier: groups whose members cast into each other for every value.
_SAFE_INTEGERS = frozenset(
    {"TINYINT", "SMALLINT", "MEDIUMINT", "INT", "INTEGER", "BIGINT", "INT1", "INT2", "INT4"}
    | {"INT8", "LONG", "SHORT", "SIGNED", "SERIAL", "BIGSERIAL", "SMALLSERIAL", "SERIAL2"}
    | {"SERIAL4", "SERIAL8"}
)
_EXACT_PARAMS = frozenset({"DECIMAL", "NUMERIC", "DEC", "FIXED", "NUMBER"})
_PARAMS = re.compile(r"\(([^)]*)\)")
_COMPOSITE = frozenset({"STRUCT", "MAP", "LIST", "ARRAY", "UNION", "ROW"})
_TIME_ZONE = {"TIMESTAMPTZ": "TIMESTAMP", "TIMETZ": "TIME"}


def base_type(column_type: str) -> str:
    """Return the type name without size, collation or modifiers, upper case."""
    return re.split(r"[\s(\[]", column_type.strip().upper(), maxsplit=1)[0]


def is_composite(column_type: str) -> bool:
    """Tell whether a type is an array, list, struct, map or union."""
    return "[" in column_type or base_type(column_type) in _COMPOSITE


def literal_kind(column_type: str) -> str | None:
    """Return the literal kind a column takes: `number`, `text`, or None (neither)."""
    base = base_type(column_type)
    if is_composite(column_type):
        return None
    if base in INTEGER_TYPES or base in DECIMAL_TYPES:
        return NUMBER
    return TEXT if base in TEXT_TYPES else None


def cast_group(column_type: str) -> str:
    """Return the cast-safe group of a type; `""` if unknown.

    Signed integers of at most 64 bits form one group, character types another;
    any other type (unsigned, wider, exact or approximate decimal, money, time
    zone aware, ...) is a group of its own: its base name, a DECIMAL / NUMERIC
    with its precision and scale, then UNSIGNED or WITH TIME ZONE when marked.
    An array, struct or map is a group of its whole spelling.
    """
    upper = " ".join(column_type.upper().split())
    if is_composite(upper):
        return re.sub(r"\s*([(),\[\]])\s*", r"\1", upper)
    words = upper.split()
    base = base_type(upper)
    if "UNSIGNED" in words or "ZEROFILL" in words:
        return f"{_exact(base, upper)} UNSIGNED"
    if base in _TIME_ZONE or "WITH TIME ZONE" in upper:
        return f"{_TIME_ZONE.get(base, base)} WITH TIME ZONE"
    if base in _SAFE_INTEGERS:
        return "integer"
    if base in TEXT_TYPES:
        return "character"
    return _exact(base, upper)


def _exact(base: str, upper: str) -> str:
    if base not in _EXACT_PARAMS:
        return base
    params = _PARAMS.search(upper)
    return base + (f"({params.group(1).replace(' ', '')})" if params else "")
