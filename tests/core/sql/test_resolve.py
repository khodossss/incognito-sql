"""Name resolution and column lineage through CTEs, derived tables and stars."""

import pytest
from sqlglot import exp

from incognito_sql.core.config import ColumnClass, Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.resolve import ColumnRef, qualify_tree, source_of

from .conftest import CATALOG, DECL, DIALECTS, Outcome, PolicyRun, summary

CASES: list[tuple[str, Outcome]] = [
    # names
    ("SELECT id FROM people, orders", Reason.AMBIGUOUS_COLUMN),
    ("SELECT x.id FROM people p, orders x JOIN people q ON q.id = id", Reason.AMBIGUOUS_COLUMN),
    ("SELECT nope FROM people", Reason.UNKNOWN_COLUMN),
    ("SELECT count(*) FROM nosuch", Reason.UNKNOWN_COLUMN),
    ("SELECT q.id FROM people p", Reason.UNKNOWN_COLUMN),
    ("SELECT id FROM other.people", Reason.UNKNOWN_COLUMN),
    ("SELECT count(*) FROM other.people", Reason.UNKNOWN_COLUMN),
    # tables absent from the declaration: every column hidden, stars are not mentions
    ("SELECT a FROM audit_shadow", Reason.HIDDEN_COLUMN),
    ("SELECT count(*) FROM audit_shadow", ([], 0, 0)),
    ("SELECT * FROM people", ([], 0, 0)),
    # CTE lineage, both ways
    (
        "WITH c AS (SELECT full_name AS f FROM people) SELECT f FROM c WHERE f = 'Ivan Petrov'",
        ([0], 1, 0),
    ),
    ("WITH c AS (SELECT full_name AS f FROM people) SELECT upper(f) FROM c", Reason.PII_OPERATION),
    (
        (
            "WITH c AS (SELECT full_name AS f FROM people) SELECT id FROM orders o JOIN c "
            "ON c.f = o.note"
        ),
        Reason.PII_JOIN_WITH_OPEN,
    ),
    ("WITH c AS (SELECT notes AS n FROM people) SELECT 1 FROM c", Reason.HIDDEN_COLUMN),
    # renaming onto another column's name, or a CTE named like a table, shadows
    (
        "WITH c AS (SELECT city AS full_name FROM people) SELECT upper(full_name) FROM c",
        Reason.AMBIGUOUS_COLUMN,
    ),
    (
        "WITH people AS (SELECT city AS town FROM people) SELECT upper(town) FROM people",
        Reason.AMBIGUOUS_COLUMN,
    ),
    ("WITH c AS (SELECT city AS town FROM people) SELECT upper(town) FROM c", ([], 0, 0)),
    (
        (
            "WITH c AS (SELECT city, count(DISTINCT full_name) AS n FROM people GROUP BY city) "
            "SELECT city FROM c WHERE n > 5"
        ),
        ([], 0, 0),
    ),
    # derived tables, both ways
    ("SELECT d.f FROM (SELECT full_name AS f FROM people) d", ([0], 0, 0)),
    ("SELECT d.f FROM (SELECT full_name AS f FROM people) d ORDER BY d.f", Reason.PII_OPERATION),
    (
        "SELECT u.f FROM (SELECT city AS f FROM people UNION SELECT customer_name FROM orders) u",
        Reason.PII_JOIN_WITH_OPEN,
    ),
    (
        (
            "SELECT u.f FROM (SELECT full_name AS f FROM people UNION SELECT customer_name "
            "FROM orders) u WHERE u.f = 'Ivan Petrov'"
        ),
        ([0], 1, 0),
    ),
    # stars inside derived sources are traced by name
    ("SELECT d.full_name FROM (SELECT * FROM people) d", ([0], 0, 0)),
    ("SELECT upper(d.full_name) FROM (SELECT * FROM people) d", Reason.PII_OPERATION),
    ("SELECT d.notes FROM (SELECT * FROM people) d", Reason.HIDDEN_COLUMN),
    ("SELECT d.city FROM (SELECT p.* FROM people p) d", ([], 0, 0)),
    ("SELECT d.id FROM (SELECT * FROM people p, orders o) d", Reason.AMBIGUOUS_COLUMN),
    (
        "SELECT f FROM (SELECT full_name AS f FROM people) d, (SELECT city AS f FROM people) e",
        Reason.AMBIGUOUS_COLUMN,
    ),
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "expected"), CASES)
def test_resolution(policy: PolicyRun, dialect: str, sql: str, expected: Outcome) -> None:
    assert summary(policy(sql, dialect)) == expected


@pytest.mark.parametrize(("dialect", "db"), [("postgres", "public"), ("sqlite", "main")])
def test_default_schema_is_allowed(policy: PolicyRun, dialect: str, db: str) -> None:
    sql = f"SELECT full_name FROM {db}.people"  # noqa: S608
    assert summary(policy(sql, dialect)) == ([0], 0, 0)


def test_mysql_database_name_is_unknown() -> None:
    tree = parse("SELECT id FROM shop.people", "mysql", Limits())
    with pytest.raises(Rejection) as info:
        qualify_tree(tree, CATALOG, "mysql")
    assert info.value.reason is Reason.UNKNOWN_COLUMN
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


def test_source_of_follows_cte_to_base_column() -> None:
    sql = "WITH c AS (SELECT full_name AS f FROM people) SELECT d.f FROM (SELECT f FROM c) d"
    tree = qualify_tree(parse(sql, "postgres", Limits()), CATALOG, "postgres")
    outer = tree.expressions[0].this
    assert isinstance(outer, exp.Column)
    ref = source_of(outer, tree, CATALOG, DECL)
    assert ref == ColumnRef("people", "full_name", ColumnClass.IDENTIFIER)


def test_case_kept_names_resolve_as_written() -> None:
    catalog = Catalog(columns={"Clients": {"FullName": "TEXT"}})
    tree = parse('SELECT "FullName" FROM "Clients"', "postgres", Limits())
    qualified = qualify_tree(tree, catalog, "postgres")
    assert qualified.sql("postgres") == (
        'SELECT clients."FullName" AS "FullName" FROM "Clients" AS clients'
    )


def test_qualify_keeps_input_tree() -> None:
    tree = parse("SELECT full_name FROM people", "postgres", Limits())
    before = tree.sql()
    qualify_tree(tree, CATALOG, "postgres")
    assert tree.sql() == before
