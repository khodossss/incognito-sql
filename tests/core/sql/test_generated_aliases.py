"""A name qualify gives an unaliased value is not the model's alias: it shadows nothing."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import DIALECTS, PolicyRun, PrepareRun, summary


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    ["SELECT CAST(city AS TEXT) FROM people", "SELECT CAST(people.city AS TEXT) FROM people"],
)
def test_an_unaliased_cast_is_answered(policy: PolicyRun, sql: str, dialect: str) -> None:
    assert summary(policy(sql, dialect)) == ([], 0, 0)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_a_hidden_column_under_a_cast_names_its_reason(policy: PolicyRun, dialect: str) -> None:
    assert policy("SELECT CAST(notes AS TEXT) FROM people", dialect) == Reason.HIDDEN_COLUMN


@pytest.mark.parametrize("dialect", DIALECTS)
def test_a_written_alias_still_may_not_shadow(policy: PolicyRun, dialect: str) -> None:
    sql = "SELECT CAST(id AS TEXT) AS city FROM people"
    assert policy(sql, dialect) == Reason.AMBIGUOUS_COLUMN


@pytest.mark.parametrize("dialect", DIALECTS)
def test_an_unaliased_cast_passes_the_rewrite(prepare_sql: PrepareRun, dialect: str) -> None:
    prepared = prepare_sql("SELECT CAST(city AS TEXT) FROM people", dialect)
    assert "CAST" in prepared.sql.upper()
