"""SQL text for the bench world on each DBMS: types, tables, rows and the field declaration."""

from collections.abc import Iterable
from datetime import date, datetime

from bench.schema import MOOD, Column

Rows = tuple[tuple[object, ...], ...]


def literal(value: object) -> str:
    """Render one invented value as an SQL literal every DBMS reads the same way."""
    if isinstance(value, datetime):
        return f"'{value.isoformat(sep=' ')}'"
    if isinstance(value, date | str):
        return "'" + str(value).replace("'", "''") + "'"
    return str(value)


def create_type(dialect: str, labels: Iterable[str]) -> list[str]:
    """Return the CREATE TYPE of the user-defined ENUM, on the DBMS that has one."""
    if dialect not in {"postgres", "duckdb"}:
        return []
    return [f"CREATE TYPE {MOOD} AS ENUM ({', '.join(map(literal, labels))})"]


def table_sql(
    name: str, columns: tuple[Column, ...], rows: Rows, dialect: str, labels: list[str]
) -> list[str]:
    """Return CREATE TABLE and INSERT for the columns that exist on ``dialect``."""
    kept = [i for i, c in enumerate(columns) if c.type_on(dialect)]
    enum = ", ".join(map(literal, labels))
    cols = ", ".join(
        f"{columns[i].quoted(dialect)} {columns[i].type_on(dialect).format(labels=enum)}"
        for i in kept
    )
    values = ", ".join("(" + ", ".join(literal(row[i]) for i in kept) + ")" for row in rows)
    return [
        f"CREATE TABLE {name} ({cols})",
        f"INSERT INTO {name} VALUES {values}",  # noqa: S608 -- invented rows
    ]


def declaration(  # noqa: PLR0913 -- the world's parts, then how the gateway runs
    tables: Iterable[tuple[str, tuple[Column, ...]]],
    dialect: str,
    *,
    web: bool,
    protection: str = "strict",
    entities: Iterable[str] = ("users",),
    row_rules: Iterable[str] = (),
) -> str:
    """Return the YAML field declaration; undeclared columns and tables stay hidden.

    Each entity table's key is ``id``; ``row_rules`` are YAML flow mappings.
    """
    lines = [
        "dsn_env: BENCH_DSN",
        f"dialect: {dialect}",
        f"web_enabled: {'true' if web else 'false'}",
        # The corpus is many queries, not a series of probes: the budgets stay out of its way,
        # and the query rate is a brake, not a bound.
        "limits: {literal_budget: 1000000, probe_budget: 1000000, query_rate: 1000000}",
        f"protection: {protection}",  # corpus expectations are written for strict
        "entities:",
        *(f"  - {{table: {name}, pk: id}}" for name in entities),
        "columns:",
    ]
    for name, columns in tables:
        marked = [f'"{c.name}": {c.cls}' for c in columns if c.cls and c.type_on(dialect)]
        if marked:
            lines.append(f"  {name}: {{{', '.join(marked)}}}")
    rules = [f"  - {rule}" for rule in row_rules]
    return "\n".join([*lines, *(["row_rules:", *rules] if rules else [])]) + "\n"
