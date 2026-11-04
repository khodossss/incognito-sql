"""Literals and tokens become bind parameters; the SQL is regenerated without comments."""

import re
from decimal import Decimal

import pytest

from incognito_sql.core.config import ColumnClass, Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.tokens.store import TokenStore

from .conftest import DECL, DIALECTS, NOW, PrepareRun

PLACEHOLDER = re.compile(r":(p\d+)")


def placeholders(sql: str) -> set[str]:
    return set(PLACEHOLDER.findall(sql))


def test_token_becomes_bind_variants(store: TokenStore, prepare_sql: PrepareRun) -> None:
    tok = store.tokenize("Ivan Petrov", NOW)
    store.tokenize("ivan petrov ", NOW)
    p = prepare_sql("SELECT id FROM people WHERE full_name = '" + tok + "'")  # noqa: S608
    assert "tk_" not in p.sql
    assert "Ivan" not in p.sql
    assert sorted(map(str, p.params.values())) == ["Ivan Petrov", "ivan petrov "]
    assert "people.full_name IN (:p0, :p1)" in p.sql


def test_comments_never_reach_sql(prepare_sql: PrepareRun) -> None:
    sql = prepare_sql("SELECT id /* a */ FROM people -- x\n WHERE city = 'Zqtown' /* b */").sql
    assert "--" not in sql
    assert "/*" not in sql


@pytest.mark.parametrize("dialect", DIALECTS)
def test_literal_expands_to_known_raw_forms(
    store: TokenStore, prepare_sql: PrepareRun, dialect: str
) -> None:
    store.tokenize("Ivan Petrov", NOW)
    p = prepare_sql("SELECT id FROM people WHERE full_name = 'IVAN PETROV'", dialect)
    assert list(p.params.values()) == ["IVAN PETROV", "Ivan Petrov"]
    assert "PETROV" not in p.sql
    assert placeholders(p.sql) == set(p.params) == {"p0", "p1"}


def test_in_mixing_tokens_and_literals_is_deduplicated(
    store: TokenStore, prepare_sql: PrepareRun
) -> None:
    tok = store.tokenize("Ivan Petrov", NOW)
    store.tokenize("ivan petrov ", NOW)
    sql = f"SELECT id FROM people WHERE full_name IN ('{tok}', 'Ivan Petrov', 'Zq Other')"  # noqa: S608
    p = prepare_sql(sql)
    assert list(p.params.values()) == ["Ivan Petrov", "ivan petrov ", "Zq Other"]
    assert "people.full_name IN (:p0, :p1, :p2)" in p.sql


def test_unknown_token_is_rejected(prepare_sql: PrepareRun) -> None:
    with pytest.raises(Rejection) as exc:
        prepare_sql("SELECT id FROM people WHERE full_name = 'tk_abcdefghijklmnop'")
    assert exc.value.reason is Reason.INVALID_TOKEN


def test_expansion_past_max_in_items_is_not_counted(
    store: TokenStore, prepare_sql: PrepareRun
) -> None:
    tok = store.tokenize("Ivan Petrov", NOW)
    store.tokenize("ivan petrov ", NOW)
    decl = DECL.model_copy(update={"limits": Limits(max_in_items=2)})
    sql = f"SELECT id FROM people WHERE full_name IN ('{tok}', 'Zq Other')"  # noqa: S608
    assert len(prepare_sql(sql, decl=decl).params) == 3
    at_limit = f"SELECT id FROM people WHERE full_name = '{tok}'"  # noqa: S608
    assert len(prepare_sql(at_limit, decl=decl).params) == 2


def test_numeric_column_variants_are_coerced(store: TokenStore, prepare_sql: PrepareRun) -> None:
    tok = store.tokenize("5550101", NOW)
    store.tokenize(" 5550101", NOW)
    store.tokenize("Zq5550101", NOW)  # another value: not a variant
    p = prepare_sql(f"SELECT id FROM people WHERE phone = '{tok}'")  # noqa: S608
    assert p.params == {"p0": 5550101}
    assert prepare_sql("SELECT id FROM people WHERE phone = 5550101").params == {"p0": 5550101}


def test_token_without_a_numeric_form_matches_nothing(
    store: TokenStore, prepare_sql: PrepareRun
) -> None:
    tok = store.tokenize("Ivan Petrov", NOW)  # stored data: no refusal, a false comparison
    p = prepare_sql(f"SELECT id FROM people WHERE phone = '{tok}' OR id = 2")  # noqa: S608
    assert "WHERE :p0 = :p1 OR people.id = :p2" in p.sql
    assert p.params == {"p0": 1, "p1": 0, "p2": 2}


@pytest.mark.parametrize(("dialect", "value"), [("postgres", Decimal("12.5")), ("sqlite", 12.5)])
def test_decimal_column_variants(prepare_sql: PrepareRun, dialect: str, value: object) -> None:
    columns = {**DECL.columns, "orders": {**DECL.columns["orders"]}}
    columns["orders"]["amount"] = ColumnClass.IDENTIFIER
    decl = DECL.model_copy(update={"columns": columns})
    p = prepare_sql("SELECT id FROM orders WHERE amount = 12.5", dialect, decl)
    assert p.params == {"p0": value}


@pytest.mark.parametrize("dialect", DIALECTS)
def test_every_value_literal_is_bound(prepare_sql: PrepareRun, dialect: str) -> None:
    p = prepare_sql(
        "SELECT id, 'Zq tag' AS tag FROM people WHERE city = 'Zqtown' AND id > 5 OR id = 2.5",
        dialect,
    )
    assert "'" not in p.sql
    assert sorted(map(str, p.params.values())) == ["2.5", "5", "Zq tag", "Zqtown"]
    assert placeholders(p.sql) == set(p.params)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_syntax_literals_stay(prepare_sql: PrepareRun, dialect: str) -> None:
    p = prepare_sql(
        "SELECT CAST(id AS DECIMAL(10, 2)) AS v, city FROM people ORDER BY (2) LIMIT 5 OFFSET 3",
        dialect,
    )
    assert "(10, 2)) AS v" in p.sql
    assert "ORDER BY (2)" in p.sql
    assert "LIMIT 5 OFFSET 3" in p.sql
    assert p.params == {}
    group = prepare_sql("SELECT count(*) FROM people GROUP BY (1)", dialect)
    assert "GROUP BY (1)" in group.sql
    assert group.params == {}


def test_postgres_placeholders_use_colon_names(prepare_sql: PrepareRun) -> None:
    p = prepare_sql("SELECT id FROM people WHERE city = 'Zqtown'", "postgres")
    assert "%(" not in p.sql
    assert "people.city = :p0" in p.sql


@pytest.mark.parametrize(
    "alias", ['"a--b"', '"a/*b"', '"a :x"', '"a :p0"', '"a%s"', '"a?b"', '"Zq tag"']
)
def test_comment_or_bind_marks_in_names_are_refused(prepare_sql: PrepareRun, alias: str) -> None:
    with pytest.raises(Rejection) as exc:
        prepare_sql(f"SELECT id AS {alias} FROM people WHERE full_name = 'Zq'")  # noqa: S608
    assert exc.value.reason is Reason.NODE_NOT_ALLOWED


def test_projected_token_shaped_literal_is_a_bind(prepare_sql: PrepareRun) -> None:
    p = prepare_sql("SELECT 'tk_abcdefghijklmnop' AS t FROM people")
    assert "tk_" not in p.sql
    assert p.params == {"p0": "tk_abcdefghijklmnop"}
