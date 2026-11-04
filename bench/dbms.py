"""A world on a DBMS: an admin builds it, a SELECT-only reader is what every client uses.

SQLite and DuckDB are files in a temporary directory, removed on exit; Postgres, MySQL
and SQL Server run in containers (testcontainers), stopped on exit. The benchmark and
the integration tests both open their worlds here.
"""

import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine
from testcontainers.community.mssql import SqlServerContainer
from testcontainers.community.mysql import MySqlContainer
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer

from bench.build import fill_file

READER, PASSWORD, DB = "bench_reader", "Bench_Reader_1", "world"
LIMIT_S = 10  # the benchmark reader's statement time limit, as a least-privilege role has
SERVERS = ("postgres", "mysql", "tsql")


@dataclass(frozen=True)
class Database:
    """Where the world lives and how the reader reaches it.

    ``url`` is a SQLAlchemy URL as the reader, seen from this host; ``admin`` is one as
    the owner. ``host``/``port`` are for tools that build their own URL; ``path`` is the
    file of SQLite or DuckDB. ``container`` is the DBMS container: a tool in a container
    joins its network and reaches the DBMS on ``localhost:inner_port``, as a sidecar.
    """

    dialect: str
    url: str
    host: str = ""
    port: int = 0
    path: Path | None = None
    container: str = ""
    inner_port: int = 0
    name: str = DB
    user: str = READER
    password: str = PASSWORD
    admin: str = ""


@contextmanager
def opened(
    dialect: str, statements: Sequence[str], *, limit: int | None = None
) -> Iterator[Database]:
    """Yield a database holding ``statements``, for a reader that can only SELECT.

    ``limit`` is the reader's statement time limit in seconds where the DBMS keeps one
    on the role (Postgres, MySQL); elsewhere the client enforces it.
    """
    if dialect not in SERVERS:
        with tempfile.TemporaryDirectory(prefix="world-", ignore_cleanup_errors=True) as where:
            path = Path(where) / f"world.{dialect}"
            fill_file(dialect, path, statements)
            url = f"{dialect}:///{path.as_posix()}"
            yield Database(dialect, url, path=path, admin=url)
        return
    with _STARTS[dialect](limit) as database:
        load(database, statements)
        yield database


def load(db: Database, statements: Sequence[str]) -> None:
    """Run ``statements`` as the admin; the reader can SELECT every table afterwards."""
    if db.path is not None:
        fill_file(db.dialect, db.path, statements)
        return
    grant = [f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {READER}"]
    _run(db.admin, [*statements, *(grant if db.dialect == "postgres" else [])])


def _run(url: str, sql: list[str], *, autocommit: bool = False) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT" if autocommit else None)
    try:
        with engine.begin() as conn:
            for statement in sql:
                conn.exec_driver_sql(statement)
    finally:
        engine.dispose()


def _id(container: DockerContainer) -> str:
    return str(container.get_wrapped_container().id)


@contextmanager
def _postgres(limit: int | None) -> Iterator[Database]:
    with PostgresContainer("postgres:16-alpine", driver="psycopg", dbname=DB) as pg:
        admin = pg.get_connection_url()
        role = [
            f"CREATE ROLE {READER} LOGIN PASSWORD '{PASSWORD}'",
            f"ALTER ROLE {READER} SET timezone = 'America/New_York'",
            f"GRANT USAGE ON SCHEMA public TO {READER}",
        ]
        if limit is not None:
            role.append(f"ALTER ROLE {READER} SET statement_timeout = '{limit}s'")
        _run(admin, role)
        host, port = pg.get_container_host_ip(), int(pg.get_exposed_port(5432))
        url = f"postgresql+psycopg://{READER}:{PASSWORD}@{host}:{port}/{DB}"
        yield Database("postgres", url, host, port, None, _id(pg), 5432, admin=admin)


@contextmanager
def _mysql(limit: int | None) -> Iterator[Database]:
    with MySqlContainer("mysql:8.4", dialect="pymysql", dbname=DB) as my:
        admin = my.get_connection_url()
        root = admin.replace(f"{my.username}:{my.password}", f"root:{my.root_password}")
        user = [
            f"CREATE USER '{READER}' IDENTIFIED BY '{PASSWORD}'",
            f"GRANT SELECT ON {DB}.* TO '{READER}'",
        ]
        if limit is not None:
            user.append(f"SET GLOBAL max_execution_time = {limit * 1000}")
        _run(root, user)
        host, port = my.get_container_host_ip(), int(my.get_exposed_port(3306))
        url = f"mysql+pymysql://{READER}:{PASSWORD}@{host}:{port}/{DB}"
        yield Database("mysql", url, host, port, None, _id(my), 3306, admin=admin)


@contextmanager
def _mssql(_limit: int | None) -> Iterator[Database]:
    image = "mcr.microsoft.com/mssql/server:2022-latest"
    with SqlServerContainer(image, dialect="mssql+pymssql") as ms:
        master = ms.get_connection_url()
        login = f"CREATE LOGIN {READER} WITH PASSWORD = '{PASSWORD}', CHECK_POLICY = OFF"
        _run(master, [f"CREATE DATABASE {DB}", login], autocommit=True)
        admin = master.rsplit("/", 1)[0] + f"/{DB}"
        user = [f"CREATE USER {READER} FOR LOGIN {READER}"]
        user.append(f"ALTER ROLE db_datareader ADD MEMBER {READER}")
        _run(admin, user)
        host, port = ms.get_container_host_ip(), int(ms.get_exposed_port(1433))
        url = f"mssql+pymssql://{READER}:{PASSWORD}@{host}:{port}/{DB}"
        yield Database("tsql", url, host, port, None, _id(ms), 1433, admin=admin)


_STARTS: dict[str, Callable[[int | None], AbstractContextManager[Database]]] = {
    "postgres": _postgres,
    "mysql": _mysql,
    "tsql": _mssql,
}
