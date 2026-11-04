"""Column types as reflection reports them: a DuckDB file, and SQLAlchemy types of other DBMS."""

from pathlib import Path
from typing import Any

import duckdb
from sqlalchemy import DateTime
from sqlalchemy.dialects import mssql, mysql, postgresql
from sqlalchemy.types import TypeEngine

from incognito_sql.core.db import make_engine
from incognito_sql.core.sql.catalog import reflect, type_text

DUCKDB_TABLE = (
    "CREATE OR REPLACE TABLE w (big BIGINT, int INTEGER, small SMALLINT, i8 INT8, huge HUGEINT,"
    " uhuge UHUGEINT, ubig UBIGINT, dec DECIMAL(10, 2), dec12 DECIMAL(12, 2), flt FLOAT,"
    " dbl DOUBLE, day DATE, day2 DATE, stamp TIMESTAMP, stamptz TIMESTAMPTZ, vc VARCHAR(20),"
    " txt TEXT, arr DECIMAL(10, 2)[])"
)


class UnknownZone(DateTime):
    """A date-time type whose time-zone flag reflection could not read."""

    def __init__(self) -> None:
        super().__init__()
        self.timezone = None  # type: ignore[assignment]


OTHER_DBMS: dict[str, TypeEngine[Any]] = {
    "unsig": mysql.BIGINT(unsigned=True),
    "udec": mysql.DECIMAL(10, 2, unsigned=True),
    "udec12": mysql.DECIMAL(12, 2, unsigned=True),
    "dec2": mysql.DECIMAL(10, 2),
    "num": postgresql.NUMERIC(10, 2),
    "money": postgresql.MONEY(),
    "money2": postgresql.MONEY(),
    "pg_ts": postgresql.TIMESTAMP(),
    "pg_tz": postgresql.TIMESTAMP(timezone=True),
    "smallmoney": mssql.SMALLMONEY(),
    "nvc": mssql.NVARCHAR(200, collation="SQL_Latin1_General_CP1_CI_AS"),
    "none": UnknownZone(),
    "none2": UnknownZone(),
}


def reflected_types(folder: Path) -> dict[str, str]:
    """Return column -> type of table `w`: DuckDB columns reflected from a file, plus others."""
    path = folder / "types.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute(DUCKDB_TABLE)
    engine = make_engine(f"duckdb:///{path.as_posix()}", "duckdb")
    try:
        found = dict(reflect(engine, "duckdb").columns["w"])
    finally:
        engine.dispose()
    return found | {name: type_text(kind) for name, kind in OTHER_DBMS.items()}
