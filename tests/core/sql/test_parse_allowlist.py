import pytest

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.allowlist import check_nodes
from incognito_sql.core.sql.parse import parse

DIALECTS = ["postgres", "sqlite", "mysql"]


def decide(sql: str, dialect: str = "postgres", limits: Limits | None = None) -> Reason | None:
    try:
        check_nodes(parse(sql, dialect, limits or Limits()))
    except Rejection as exc:
        return exc.reason
    return None


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT 1; SELECT 2", Reason.MULTIPLE_STATEMENTS),
        ("DELETE FROM people", Reason.NODE_NOT_ALLOWED),
        ("SELECT * INTO x FROM people", Reason.NODE_NOT_ALLOWED),
        ("EXPLAIN SELECT 1", Reason.NODE_NOT_ALLOWED),
        ("SELECT pg_sleep(1)", Reason.NODE_NOT_ALLOWED),
        ("/*! SELECT 1 */", Reason.PARSE_ERROR),
        ("", Reason.PARSE_ERROR),
        (";;", Reason.PARSE_ERROR),
        ("SELECT FROM WHERE", Reason.PARSE_ERROR),
        ("SELECT 'unterminated", Reason.PARSE_ERROR),
        ("SELECT " + "(" * 5000 + "1" + ")" * 5000, Reason.PARSE_ERROR),
        ("INSERT INTO people VALUES (1)", Reason.NODE_NOT_ALLOWED),
        ("UPDATE people SET city = 'x'", Reason.NODE_NOT_ALLOWED),
        ("CREATE TABLE x (a INT)", Reason.NODE_NOT_ALLOWED),
        ("WITH RECURSIVE r AS (SELECT 1) SELECT * FROM r", Reason.NODE_NOT_ALLOWED),
        ("SELECT * FROM c.s.people", Reason.NODE_NOT_ALLOWED),
        ("SELECT a FROM t NATURAL JOIN u", Reason.NODE_NOT_ALLOWED),
        ("SELECT a FROM t JOIN u USING (id)", Reason.NODE_NOT_ALLOWED),
        ("SELECT a FROM t SEMI JOIN u ON t.a = u.a", Reason.NODE_NOT_ALLOWED),
        ("SELECT a->>'k' FROM people", Reason.NODE_NOT_ALLOWED),
        ("SELECT CAST(a AS regclass) FROM people", Reason.NODE_NOT_ALLOWED),
        ("SELECT DISTINCT ON (a) a FROM people", Reason.NODE_NOT_ALLOWED),
        ("SELECT a FROM people GROUP BY ROLLUP (a)", Reason.NODE_NOT_ALLOWED),
        ("SELECT a FROM people FOR UPDATE", Reason.NODE_NOT_ALLOWED),
        ("SELECT a FROM people TABLESAMPLE SYSTEM (10)", Reason.NODE_NOT_ALLOWED),
        ("SELECT * FROM (VALUES (1)) AS v(a)", Reason.NODE_NOT_ALLOWED),
        ("SELECT string_agg(a, ',') FROM people", Reason.NODE_NOT_ALLOWED),
        ("SELECT a FROM people WHERE a = $1", Reason.NODE_NOT_ALLOWED),
        ("SELECT * FROM pg_catalog.pg_user", Reason.SYSTEM_CATALOG),
        ("SELECT * FROM pg_class", Reason.SYSTEM_CATALOG),
        ("SELECT * FROM PG_STATS", Reason.SYSTEM_CATALOG),
        ("SELECT * FROM information_schema.columns", Reason.SYSTEM_CATALOG),
        ("SELECT * FROM performance_schema.threads", Reason.SYSTEM_CATALOG),
        ("SELECT * FROM sys.objects", Reason.SYSTEM_CATALOG),
        ("SELECT * FROM mysql.user", Reason.SYSTEM_CATALOG),
        ("SELECT * FROM sqlite_master", Reason.SYSTEM_CATALOG),
        ("SELECT * FROM duckdb_tables", Reason.SYSTEM_CATALOG),
        ("SELECT pg_sleep(1) FROM pg_class", Reason.SYSTEM_CATALOG),
        ("SELECT * FROM x.pg_catalog.t", Reason.SYSTEM_CATALOG),
        ("SELECT * FROM dbstat", Reason.SYSTEM_CATALOG),
        ("SELECT * FROM pragma_table_info('people')", Reason.SYSTEM_CATALOG),
        ("SELECT {:1}", Reason.PARSE_ERROR),
        ("SELECT COUNT(DISTINCT a, b) FROM people", Reason.NODE_NOT_ALLOWED),
        ("SELECT a FROM people WHERE a IN ()", Reason.NODE_NOT_ALLOWED),
    ],
)
def test_rejected(sql: str, reason: Reason) -> None:
    assert decide(sql) == reason


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    [
        (
            "SELECT p.city AS c, COUNT(DISTINCT o.id) FROM people AS p"
            " INNER JOIN orders AS o ON o.pid = p.id LEFT JOIN x ON x.a = p.a"
            " WHERE p.age >= 18 AND p.city IN ('A', 'B') AND p.x IS NOT NULL"
            " AND NOT p.y LIKE 'a%' AND p.z BETWEEN 1 AND 2"
            " GROUP BY p.city HAVING COUNT(*) > 2 ORDER BY 2 DESC LIMIT 10 OFFSET 5"
        ),
        (
            "WITH c AS (SELECT a FROM t) SELECT * FROM c UNION SELECT a FROM t"
            " UNION ALL SELECT b FROM u ORDER BY 1 LIMIT 3"
        ),
        (
            "SELECT CASE WHEN a > 1 THEN 'x' ELSE 'y' END, CAST(a AS VARCHAR(10)),"
            " SUBSTRING(a, 1, 2), ROUND(a, 2), TRIM(a), LENGTH(a), LOWER(a), UPPER(a), ABS(-a),"
            " COALESCE(a, b), SUM(a) / AVG(a) * 2 - MIN(a) + MAX(a), TRUE, NULL FROM t"
        ),
        (
            "SELECT a FROM t WHERE a NOT IN (SELECT b FROM u) AND EXISTS (SELECT 1 FROM u)"
            " AND a <> 1 AND a != 2 AND a < 3 AND a <= 4 AND a > 0"
        ),
        "SELECT DISTINCT s.a FROM (SELECT a FROM t) AS s, public.people",
        "SELECT t.* FROM t RIGHT JOIN u ON t.a = u.a CROSS JOIN v",
    ],
)
def test_allowed(sql: str, dialect: str) -> None:
    assert decide(sql, dialect) is None


def test_full_join_allowed() -> None:
    assert decide("SELECT a FROM t FULL OUTER JOIN u ON t.a = u.a") is None


@pytest.mark.parametrize("dialect", ["postgres", "sqlite"])
def test_ilike_allowed(dialect: str) -> None:
    assert decide("SELECT a FROM t WHERE a ILIKE 'x%'", dialect) is None
