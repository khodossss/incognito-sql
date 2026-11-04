"""Typed identifiers with edge values, in each DBMS's own SQL: tokens meet them in the probes."""

PROBES = {
    "postgres": [
        "CREATE TYPE mood AS ENUM ('calm', 'busy')",
        (
            "CREATE TABLE probes (id INTEGER, d12 NUMERIC(12, 2), num NUMERIC, txt VARCHAR(200),"
            " d10 NUMERIC(10, 0), dt DATE, ts TIMESTAMP, tz TIMESTAMPTZ, u UUID, bo BOOLEAN,"
            " mo MONEY, e mood)"
        ),
        (
            "INSERT INTO probes VALUES (1, 5.50, 1e30, 'not a date', 5, '2020-01-01',"
            " '2020-01-01 00:00:00', '2020-01-01 00:00:00+00',"
            " '6f9619ff-8b86-d011-b42d-00c04fc964ff', true, 5, 'calm')"
        ),
        (
            "INSERT INTO probes (id, d12, num, txt) VALUES (2, 5.00, 5, 'maybe'),"
            " (3, NULL, NULL, '2020-13-45'), (4, NULL, NULL, '1e30'), (5, NULL, NULL, '2020-01-01')"
        ),
    ],
    "sqlite": [
        "CREATE TABLE probes (id INTEGER, txt TEXT, ib INTEGER, ubi UNSIGNED BIG INT)",
        (
            "INSERT INTO probes VALUES (1, '99999999999999999999', 5, 5),"
            " (2, '9223372036854775808', NULL, NULL), (3, '5', NULL, NULL)"
        ),
    ],
    "mysql": [
        (
            "CREATE TABLE probes (id INT, d40 DECIMAL(40, 0), neg BIGINT, d12 DECIMAL(12, 2),"
            " ub BIGINT UNSIGNED, d10 DECIMAL(10, 0), du DECIMAL(10, 2) UNSIGNED,"
            " dbu DOUBLE UNSIGNED, e ENUM('calm', 'busy'), dtf DATETIME(3), fu FLOAT UNSIGNED)"
        ),
        (
            "INSERT INTO probes VALUES (1, 100000000000000000000, -5, 5.50, 5, 5, 5.50, 5, 'calm',"
            " '2020-01-01 12:00:00.123', 5),"
            " (2, 5, 5, 5.00, NULL, NULL, NULL, NULL, NULL, NULL, NULL),"
            " (3, NULL, NULL, NULL, 18446744073709551611, NULL, NULL, NULL, NULL, NULL, NULL)"
        ),
    ],
    "duckdb": [
        (
            "CREATE TABLE probes (id INTEGER, hi HUGEINT, neg BIGINT, d12 DECIMAL(12, 2),"
            " dbl DOUBLE, txt VARCHAR, ub UBIGINT, uh UHUGEINT, d10 DECIMAL(10, 0), f FLOAT,"
            " dt DATE, ts TIMESTAMP, tz TIMESTAMPTZ, u UUID, bo BOOLEAN, e ENUM('calm', 'busy'))"
        ),
        (
            "INSERT INTO probes VALUES (1, 100000000000000000000, -5, 5.50, 1e39, 'not a date',"
            " 5, 5, 5, 5, '2020-01-01', '2020-01-01 00:00:00', '2020-01-01 00:00:00+00',"
            " '6f9619ff-8b86-d011-b42d-00c04fc964ff', true, 'calm')"
        ),
        (
            "INSERT INTO probes (id, hi, neg, d12, dbl, txt) VALUES (2, 5, 5, 5.00, 5, 'maybe'),"
            " (3, NULL, NULL, NULL, NULL, '2020-13-45'), (4, NULL, NULL, NULL, NULL, '1e30'),"
            " (5, NULL, NULL, NULL, NULL, '2020-01-01')"
        ),
    ],
    "tsql": [
        (
            "CREATE TABLE probes (id INT, d12 NUMERIC(12, 2), d38 NUMERIC(38, 0),"
            " txt NVARCHAR(200), d10 DECIMAL(10, 0), dt2 DATETIME2, dtm DATETIME,"
            " dto DATETIMEOFFSET, u UNIQUEIDENTIFIER, mo MONEY, sm SMALLMONEY, f REAL)"
        ),
        (
            "INSERT INTO probes VALUES (1, 5.50, 10000000000000000000000000000000000000,"
            " 'not a date', 5, '2020-01-01 12:00:00.123456', '2020-01-01T12:00:00',"
            " '2020-01-01 00:00:00 +00:00', '6f9619ff-8b86-d011-b42d-00c04fc964ff', 5, 5, 5)"
        ),
        (
            "INSERT INTO probes (id, d12, d38, txt) VALUES (2, 5.00, 5, 'maybe'),"
            " (3, NULL, NULL, '2020-13-45'), (4, NULL, NULL, '1e30')"
        ),
    ],
}
