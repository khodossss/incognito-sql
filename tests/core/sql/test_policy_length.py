"""length() of an identifier: an L3 fact, only where the profile admits it."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import DECL, DIALECTS, PolicyRun, PrepareRun, summary

PERMISSIVE = DECL.model_copy(update={"protection": "permissive"})
OP = Reason.PII_OPERATION
LENGTHS = [
    "SELECT length(full_name) FROM people",
    "SELECT id FROM people WHERE length(full_name) > 5",
    "SELECT length(full_name), count(*) FROM people GROUP BY length(full_name)",
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("sql", LENGTHS)
def test_length_is_permissive_only(policy: PolicyRun, sql: str, dialect: str) -> None:
    assert policy(sql, dialect) == OP
    assert policy(sql, dialect, decl=DECL.model_copy(update={"protection": "balanced"})) == OP
    assert summary(policy(sql, dialect, decl=PERMISSIVE)) == ([], 0, 0)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_a_length_leaves_as_a_number(prepare_sql: PrepareRun, dialect: str) -> None:
    prepared = prepare_sql("SELECT length(full_name) FROM people", dialect, PERMISSIVE)
    assert [str(c) for c in prepared.output_classes] == ["open"]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT length(full_name || 'x') FROM people",
        "SELECT length(upper(full_name)) FROM people",
        "SELECT length(notes) FROM people",
    ],
)
def test_only_the_bare_column_may_be_measured(policy: PolicyRun, sql: str, dialect: str) -> None:
    assert policy(sql, dialect, decl=PERMISSIVE) in {
        OP,
        Reason.NODE_NOT_ALLOWED,
        Reason.HIDDEN_COLUMN,
    }
