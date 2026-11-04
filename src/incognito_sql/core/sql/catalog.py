"""Reflection of the tables and columns the model may refer to."""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from sqlalchemy import DateTime, Engine, Enum, Time, inspect, text
from sqlalchemy.engine import Inspector
from sqlalchemy.types import TypeEngine
from sqlglot import exp
from sqlglot.dialects.dialect import Dialect


@dataclass(frozen=True)
class Catalog:
    """Default-schema tables and views: table -> column -> SQL type name.

    Names are as the dialect resolves them: folded to lower case where the DBMS
    ignores case, kept as reported where it does not (Postgres, MySQL).
    """

    columns: Mapping[str, Mapping[str, str]]
    # Primary key columns of base tables; `null_free` names the tables whose key
    # can hold no NULL (a SQLite key may, unless NOT NULL or a rowid alias).
    keys: Mapping[str, tuple[str, ...]] = MappingProxyType({})
    null_free: frozenset[str] = frozenset()
    views: frozenset[str] = frozenset()
    # Postgres partitions and child tables: table -> the tables it inherits from.
    parents: Mapping[str, frozenset[str]] = MappingProxyType({})

    def table(self, name: str) -> str | None:
        """Return the catalog name of the table called `name` in any case, or None."""
        return _find(self.columns, name)

    def column(self, table: str, name: str) -> str | None:
        """Return the catalog name of a column of a catalog table in any case, or None."""
        return _find(self.columns.get(table, {}), name)


def reflect(engine: Engine, dialect: str) -> Catalog:
    """Read tables and views of the default schema, skipping SQLite internals.

    Tables or columns whose names differ only in case are left out: the
    declaration cannot tell them apart, so the model cannot use them.
    """
    insp = inspect(engine)
    names = [*insp.get_table_names(), *insp.get_view_names()]
    tables: dict[str, Mapping[str, str]] = {}
    keys: dict[str, tuple[str, ...]] = {}
    null_free: set[str] = set()
    views = set(insp.get_view_names())
    for name in _distinct(n for n in names if not n.lower().startswith("sqlite_")):
        found = _columns(engine, name) if dialect == "duckdb" else _inspected(insp, name)
        kept = set(_distinct(column for column, _ in found))
        cols = {resolved(c, dialect): kind for c, kind in found if c in kept}
        table = resolved(name, dialect)
        tables[table] = MappingProxyType(cols)
        key = () if name in views else _key(engine, insp, name, dialect)
        if key and all(c in kept for c, _ in key):
            keys[table] = tuple(resolved(c, dialect) for c, _ in key)
            if all(safe for _, safe in key):
                null_free.add(table)
    return Catalog(
        columns=MappingProxyType(tables),
        keys=MappingProxyType(keys),
        null_free=frozenset(null_free),
        views=frozenset(t for t in tables if t in {resolved(v, dialect) for v in views}),
        parents=_parents(engine, dialect, tables),
    )


# A partition or child table holds rows its parent shows too. Only within the default schema.
_PG_PARENTS = text(
    "SELECT c.relname, p.relname FROM pg_inherits i"
    " JOIN pg_class c ON c.oid = i.inhrelid JOIN pg_class p ON p.oid = i.inhparent"
    " WHERE c.relnamespace = p.relnamespace"
    " AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = current_schema())"
)


def _parents(
    engine: Engine, dialect: str, tables: Mapping[str, object]
) -> Mapping[str, frozenset[str]]:
    if dialect != "postgres":
        return MappingProxyType({})
    found: dict[str, set[str]] = {}
    with engine.connect() as conn:
        for child, parent in conn.execute(_PG_PARENTS):
            if child in tables and parent in tables:
                found.setdefault(str(child), set()).add(str(parent))
    return MappingProxyType({child: frozenset(up) for child, up in found.items()})


def _key(engine: Engine, insp: Inspector, table: str, dialect: str) -> list[tuple[str, bool]]:
    # Each primary key column and whether it can hold no NULL. Any failure: no key.
    try:
        if dialect == "sqlite":
            return _sqlite_key(engine, table)
        cols = insp.get_pk_constraint(table).get("constrained_columns") or []
    except Exception:  # noqa: BLE001 -- a key is an optimisation; without it, refuse as before
        return []
    return [(str(c), True) for c in cols]  # outside SQLite a primary key is NOT NULL


def _sqlite_key(engine: Engine, table: str) -> list[tuple[str, bool]]:
    quoted = exp.to_identifier(table, quoted=True).sql(dialect="sqlite")
    with engine.connect() as conn:
        rows = list(conn.exec_driver_sql(f"PRAGMA table_info({quoted})"))
        ddl = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).scalar()
    key = sorted((r[5], str(r[1]), str(r[2]).upper(), bool(r[3])) for r in rows if r[5])
    # A rowid alias cannot hold NULL; `PRIMARY KEY DESC` and WITHOUT ROWID tables have none.
    text_ddl = str(ddl or "").upper()
    plain = "DESC" not in text_ddl and "WITHOUT ROWID" not in text_ddl
    rowid = len(key) == 1 and key[0][2] == "INTEGER" and plain
    return [(name, notnull or rowid) for _, name, _, notnull in key]


def _inspected(insp: Inspector, table: str) -> list[tuple[str, str]]:
    return [(c["name"], type_text(c["type"])) for c in insp.get_columns(table)]


def type_text(kind: TypeEngine[Any]) -> str:
    """Return a reflected type as SQL, with the flags its name leaves out.

    `UNSIGNED`, MySQL's fractional seconds precision (`DATETIME(3)`) and `WITH TIME
    ZONE` are added from the type's attributes; a date
    or time type whose time-zone flag is unknown gets `""`, a type matching nothing;
    an enumerated type is `ENUM` (SQLAlchemy writes some as VARCHAR).
    """
    if isinstance(kind, Enum):
        return "ENUM"
    name = str(kind).upper()  # SQLAlchemy >= 2.1 writes no precision and no time zone here
    fsp = getattr(kind, "fsp", None)
    if isinstance(fsp, int):
        name += f"({fsp})"
    if getattr(kind, "unsigned", False) is True:
        name += " UNSIGNED"
    if isinstance(kind, DateTime | Time):
        zone = getattr(kind, "timezone", None)
        if not isinstance(zone, bool):
            return ""
        if zone:
            name += " WITH TIME ZONE"
    return name


def _columns(engine: Engine, table: str) -> list[tuple[str, str]]:
    # duckdb-engine's column reflection queries pg_collation, which DuckDB lacks.
    sql = text(
        "SELECT column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = current_schema() AND table_name = :t ORDER BY ordinal_position"
    )
    with engine.connect() as conn:
        return [
            (str(n), str(t)) for n, t in conn.execute(sql, {"t": table})
        ]  # ENUM labels keep case


def resolved(name: str, dialect: str) -> str:
    """Return a name as the dialect resolves it when it is written quoted."""
    ident = exp.to_identifier(name, quoted=True)
    return Dialect.get_or_raise(dialect).normalize_identifier(ident).name


def _distinct(names: Iterable[str]) -> list[str]:
    listed = list(names)
    folded = Counter(n.casefold() for n in listed)
    return [n for n in listed if folded[n.casefold()] == 1]


def _find(names: Mapping[str, object], name: str) -> str | None:
    folded = name.casefold()
    return next((n for n in names if n.casefold() == folded), None)
