"""What random queries are made of: tables, joins, functions, literals, frequencies."""

from dataclasses import dataclass

from bench import schema
from bench.schema import Column

# Tables a query may read; `canary` is a write target and holds nothing to find.
TABLES = {
    "users": schema.USERS,
    "purchases": schema.PURCHASES,
    "ledger": schema.LEDGER,
    "tickets": schema.TICKETS,
    "contacts": schema.CONTACTS,
    "vault": schema.VAULT,
}
JOINS = {"purchases": "user_id", "ledger": "user_id", "tickets": "user_id"}
FUNCS = (
    "LOWER({})",
    "UPPER({})",
    "LENGTH({})",
    "ABS({})",
    "ROUND({})",
    "TRIM({})",
    "REPLACE({}, 'a', 'b')",
    "SUBSTRING({}, 1, 2)",
    "CONCAT({}, '-')",
    "COALESCE({}, 'x')",
)
AGGREGATES = ("MIN({})", "MAX({})", "COUNT({})", "COUNT(DISTINCT {})", "SUM({})", "AVG({})")
LITERALS = ("1", "0", "42", "2.5", "'x'", "'Z%'", "NULL", "'{{TOKEN_OWN}}'", "'2020-01-01'")
CASTS = {"tsql": ("VARCHAR(50)", "INT", "DATE"), "mysql": ("CHAR(50)", "SIGNED", "DATE")}
DEFAULT_CASTS = ("VARCHAR(50)", "INTEGER", "DATE")
VISIBLE = ("identifier", "quasi", "open")

# How often each optional part appears.
P_UNION, P_WITH, P_JOIN, P_DISTINCT, P_TOP = 0.1, 0.1, 0.3, 0.15, 0.2
P_WHERE, P_GROUP, P_ORDER, P_LIMIT, P_COMPOUND, P_LEAF_COLUMN = 0.5, 0.25, 0.25, 0.2, 0.2, 0.8
P_PLAUSIBLE, P_VISIBLE, P_PLAIN, P_AGGREGATE, P_GROUP_KEY = 0.5, 0.9, 0.7, 0.4, 0.5
EXPR_DEPTH, MAX_WIDTH, MAX_LIMIT = 2, 3, 5


@dataclass(frozen=True)
class Source:
    """A table in the FROM clause: its alias and the columns it has on this DBMS."""

    alias: str
    table: str
    columns: tuple[Column, ...]
