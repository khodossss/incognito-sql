"""The bench world's tables: columns, their SQL type on each DBMS, and disclosure classes."""

from dataclasses import dataclass, field

DIALECTS = ("postgres", "sqlite", "mysql", "duckdb", "tsql")


@dataclass(frozen=True)
class Column:
    """A column, its SQL type and its disclosure class (None: undeclared, hence hidden).

    ``types`` overrides ``sql_type`` per DBMS; a DBMS mapped to ``""`` has no such column.
    """

    name: str
    sql_type: str
    cls: str | None
    types: dict[str, str] = field(default_factory=dict, compare=False, hash=False)

    def type_on(self, dialect: str) -> str:
        """Return the column's SQL type on ``dialect``; empty when the DBMS lacks it."""
        return self.types.get(dialect, self.sql_type)

    def quoted(self, dialect: str) -> str:
        """Return the column name as DDL on ``dialect`` spells it."""
        if self.name.isidentifier() and self.name.islower():
            return self.name
        quotes = {"mysql": "``", "tsql": "[]"}.get(dialect, '""')
        return quotes[0] + self.name + quotes[1]


def _cols(*specs: str) -> tuple[Column, ...]:
    out = []
    for spec in specs:
        name, sql_type, cls = spec.split(":")
        out.append(Column(name, sql_type.replace("_", " "), cls or None))
    return tuple(out)


def _only(name: str, cls: str, **types: str) -> Column:
    """Return a column that exists only on the DBMS named, with its type there."""
    return Column(name, "", cls, types)


USERS = _cols(
    "id:INTEGER_PRIMARY_KEY:open",
    "name:VARCHAR(200):identifier",
    "email:VARCHAR(200):identifier",
    "phone:BIGINT:identifier",
    "city:VARCHAR(200):quasi",
    "tier:VARCHAR(200):open",
    "bio:VARCHAR(400):free_text",
    "password_hash:VARCHAR(200):secret",
    "ssn:VARCHAR(200):",
)
PURCHASES = _cols(
    "id:INTEGER_PRIMARY_KEY:open",
    "user_id:INTEGER:open",
    "buyer_email:VARCHAR(200):identifier",
    "total:NUMERIC(10,2):open",
    "note:VARCHAR(200):",
)
CONTACTS = _cols("id:INTEGER:open", "email:VARCHAR(200):")
TICKETS = _cols("id:INTEGER:open", "user_id:INTEGER:open", "body:VARCHAR(400):free_text")
VAULT = _cols("id:INTEGER:", "api_key:VARCHAR(200):")
CANARY = _cols("id:INTEGER:")  # a write target: its one row must survive the corpus
# A table of people under rules on rows, and a table that names them: its labels give
# the keys of PATIENTS, and must give none of a row or a name a rule hides.
PATIENTS = _cols(
    "id:INTEGER_PRIMARY_KEY:open", "full_name:VARCHAR(200):identifier", "ward:VARCHAR(200):open"
)
VISITS = _cols(
    "id:INTEGER_PRIMARY_KEY:open", "patient_name:VARCHAR(200):identifier", "room:VARCHAR(40):open"
)
MOOD = "bench_mood"  # the user-defined ENUM type on Postgres and DuckDB
# Typed identifiers: each type the DBMS has, so cross-type rules are exercised everywhere.
LEDGER = (
    *_cols(
        "id:INTEGER_PRIMARY_KEY:open",
        "user_id:INTEGER:open",
        "amount:DECIMAL(12,2):identifier",
        "amount_b:DECIMAL(12,2):identifier",
        "born:DATE:identifier",
    ),
    Column("seen_at", "TIMESTAMP", "identifier", {"mysql": "DATETIME", "tsql": "DATETIME2(0)"}),
    _only(
        "seen_tz",
        "identifier",
        postgres="TIMESTAMPTZ",
        duckdb="TIMESTAMPTZ",
        tsql="DATETIMEOFFSET(0)",
    ),
    _only("cash", "identifier", tsql="MONEY"),
    _only("huge", "identifier", duckdb="HUGEINT"),
    _only("unsigned_no", "identifier", mysql="BIGINT UNSIGNED"),
    _only("mood", "identifier", postgres=MOOD, duckdb=MOOD, mysql="ENUM({labels})"),
    Column("Odd Name", "VARCHAR(40)", "open"),  # mixed case and a space: needs quoting
)
