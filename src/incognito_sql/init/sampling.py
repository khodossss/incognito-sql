"""Local sampling of column values; the values stay in memory and are never shown."""

from sqlalchemy import Engine, text
from sqlglot import exp

from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.rewrite import render

MAX_SAMPLES = 100


def sample(
    engine: Engine, catalog: Catalog, dialect: str
) -> tuple[dict[tuple[str, str], list[object]], frozenset[tuple[str, str]]]:
    """Read up to 100 non-null values per column; return them and the columns that failed."""
    found: dict[tuple[str, str], list[object]] = {}
    missed: set[tuple[str, str]] = set()
    with engine.connect() as conn:
        for table, cols in catalog.columns.items():
            for column in cols:
                sql = text(_sample_sql(table, column, dialect))
                try:
                    found[table, column] = [row[0] for row in conn.execute(sql)]
                except Exception:  # noqa: BLE001 -- the message may quote values
                    conn.rollback()
                    missed.add((table, column))
    return found, frozenset(missed)


def _sample_sql(table: str, column: str, dialect: str) -> str:
    # Reflected names, quoted: a reserved word or a mixed-case name is still that name.
    col = exp.column(exp.to_identifier(column, quoted=True))
    tree = (
        exp.select(col)
        .from_(exp.Table(this=exp.to_identifier(table, quoted=True)))
        .where(exp.Not(this=exp.Is(this=col.copy(), expression=exp.Null())))
        .limit(MAX_SAMPLES)
    )
    return render(tree, dialect)
