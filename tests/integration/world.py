"""The invented world: people, orders, cards, staff and a table with mixed-case names."""

import sqlglot

from .world_probes import PROBES

# Written for Postgres, transpiled to each dialect: quoted names keep their case.
WORLD = [
    (
        "CREATE TABLE people (id INTEGER PRIMARY KEY, full_name VARCHAR(200), city VARCHAR(200),"
        " bio VARCHAR(200), secret_note VARCHAR(200), phone BIGINT)"
    ),
    (
        "INSERT INTO people VALUES (1, 'Ivan Petrov', 'Haifa', 'b1', 'Zzsecret one', 501234567),"
        " (2, 'Anna Ivanova', 'Haifa', 'b2', 'n2', 527654321),"
        " (3, 'Zqcanary Person', 'Eilat', 'Zqcanary bio', 'Zqcanary', 549999999)"
    ),
    (
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, person_id INTEGER,"
        " customer_name VARCHAR(200), amount NUMERIC(10, 2))"
    ),
    (
        "INSERT INTO orders VALUES (10, 1, 'Ivan Petrov', 100), (11, 3, 'Zqcanary Person', 250),"
        " (12, 3, 'zqcanary person', 5)"
    ),
    "CREATE TABLE cards (card_no VARCHAR(40) PRIMARY KEY, holder VARCHAR(200))",
    "INSERT INTO cards VALUES ('4111111111111111', 'Zqcanary Person'), ('c-7', 'Zqcanary Person')",
    "CREATE TABLE staff (id INTEGER, login VARCHAR(200))",
    "INSERT INTO staff VALUES (1, 'Zqcanary admin')",
    (
        'CREATE TABLE "Clients" ("ClientId" INTEGER PRIMARY KEY, "FullName" VARCHAR(200),'
        ' "Town" VARCHAR(200))'
    ),
    "INSERT INTO \"Clients\" VALUES (7, 'Ivan Petrov', 'Haifa'), (8, 'Zqcanary Person', 'Eilat')",
]
# Two tables whose names differ only in case, where the DBMS keeps them apart.
TWINS = ['CREATE TABLE "Twin" (id INTEGER, note VARCHAR(200))', "CREATE TABLE twin (id INTEGER)"]


# Wide and odd numeric identifiers, in the DBMS's own SQL: casts between them can fail.
NATIVE = {
    "postgres": [
        "CREATE TABLE wallets (id INTEGER, m MONEY)",
        "INSERT INTO wallets VALUES (1, 12.50), (2, 7)",
        "CREATE TABLE moments (id INTEGER, ts TIMESTAMP, tz TIMESTAMPTZ, seen TIMESTAMPTZ)",
        (
            "INSERT INTO moments VALUES (1, '2020-01-01 00:00:00', '2020-01-01 00:00:00+00',"
            " '2020-01-01 00:00:00+00'), (2, '294276-12-31 23:00:00', '2020-01-02 00:00:00+00',"
            " '2020-01-02 00:00:00+00')"
        ),
    ],
    "mysql": [
        "CREATE TABLE wide (id INT, ub BIGINT UNSIGNED, b BIGINT, ui INT UNSIGNED)",
        "INSERT INTO wide VALUES (1, 18446744073709551615, 1, 4294967295), (2, 5, 5, 5)",
    ],
    "tsql": [
        "CREATE TABLE wide (id INT, num BIGINT, m MONEY, i INT, sm SMALLMONEY)",
        "INSERT INTO wide VALUES (1, 10000000000000000, 1, 300000, 1)",
    ],
    "duckdb": [
        (
            "CREATE TABLE wide (id INTEGER, h HUGEINT, d DECIMAL(10, 2), uh UHUGEINT, b BIGINT,"
            " ub UBIGINT)"
        ),
        (
            "INSERT INTO wide VALUES (1, 100000000000000000000, 1, 18446744073709551616, 1,"
            " 18446744073709551615), (2, 5, 5, 5, 5, 5)"
        ),
        "CREATE TABLE moments (id INTEGER, ts TIMESTAMP, tz TIMESTAMPTZ, seen TIMESTAMPTZ)",
        (
            "INSERT INTO moments VALUES (1, '2020-01-01 00:00:00', '2020-01-01 00:00:00+00',"
            " '2020-01-01 00:00:00+00'), (2, '290309-12-22 (BC) 00:00:00',"
            " '2020-01-02 00:00:00+00', '2020-01-02 00:00:00+00')"
        ),
    ],
}


def statements(dialect: str) -> list[str]:
    """Return the world's DDL and rows in the dialect's SQL."""
    extra = TWINS if dialect in {"postgres", "mysql"} else []
    common = [sqlglot.transpile(s, read="postgres", write=dialect)[0] for s in WORLD + extra]
    return common + NATIVE.get(dialect, []) + PROBES[dialect]
