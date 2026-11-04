"""Names in the regenerated SQL are plain identifiers; equal literals share one bind."""

from decimal import Decimal

import pytest

from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.tokens.store import TokenStore

from .conftest import DIALECTS, NOW, PrepareRun


def test_bind_mark_in_alias_cannot_smuggle_a_variant(
    store: TokenStore, prepare_sql: PrepareRun
) -> None:
    tok = store.tokenize("Ivan Petrov", NOW)
    with pytest.raises(Rejection) as exc:
        prepare_sql(f"""SELECT id AS "y :p0" FROM people WHERE full_name = '{tok}'""")  # noqa: S608
    assert exc.value.reason is Reason.NODE_NOT_ALLOWED


@pytest.mark.parametrize(
    "sql",
    [
        'SELECT p.id FROM people AS "P q" JOIN people p ON p.id = p.id',
        'WITH "c c" AS (SELECT id FROM people) SELECT id FROM "c c"',
        'SELECT d."1" FROM (SELECT 1) AS d',
    ],
)
def test_names_outside_the_plain_shape_are_refused(prepare_sql: PrepareRun, sql: str) -> None:
    with pytest.raises(Rejection) as exc:
        prepare_sql(sql)
    assert exc.value.reason in {Reason.NODE_NOT_ALLOWED, Reason.UNKNOWN_COLUMN}


@pytest.mark.parametrize("dialect", DIALECTS)
def test_names_qualify_derives_from_values_are_renamed(
    prepare_sql: PrepareRun, dialect: str
) -> None:
    p = prepare_sql(
        "SELECT 'Zq tag', 1.5, id FROM people p "
        "WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_name = p.full_name)",
        dialect,
    )
    assert ":p0 AS _col_0, :p1 AS _col_1, p.id AS id" in p.sql
    assert "SELECT :p2 AS _col_0 FROM orders" in p.sql


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    ("sql", "values"),
    [
        ("SELECT substring(city, 1, 2), count(*) FROM people GROUP BY 1", [1, 2]),
        (
            "SELECT CASE WHEN id > 1 THEN 'a' ELSE 'b' END, count(*) FROM people GROUP BY 1",
            [1, "a", "b"],
        ),
    ],
)
def test_group_by_copy_shares_binds(
    prepare_sql: PrepareRun, dialect: str, sql: str, values: list[object]
) -> None:
    p = prepare_sql(sql, dialect)
    assert sorted(map(str, p.params.values())) == sorted(map(str, values))
    assert all(p.sql.count(f":{name}") == 2 for name in p.params)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_equal_literals_share_and_kinds_stay_apart(prepare_sql: PrepareRun, dialect: str) -> None:
    p = prepare_sql(
        "SELECT id FROM people WHERE id = 1 OR id = 1 OR city = '1' OR id = 1.0", dialect
    )
    assert len(p.params) == 3
    assert {type(v) for v in p.params.values()} == {
        int,
        str,
        Decimal if dialect == "postgres" else float,
    }
