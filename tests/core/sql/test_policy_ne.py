"""<> over an identifier: an existence probe, in permissive."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import DECL, DIALECTS, PolicyRun, PrepareRun, summary

PERMISSIVE = DECL.model_copy(update={"protection": "permissive"})
OP = Reason.PII_OPERATION


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM people WHERE full_name <> 'Ivan Petrov'",
        "SELECT id FROM people WHERE full_name != 'Ivan Petrov'",
        "SELECT id FROM people WHERE phone <> 5550101",
    ],
)
def test_ne_is_permissive_only(policy: PolicyRun, sql: str, dialect: str) -> None:
    assert policy(sql, dialect) == OP
    assert summary(policy(sql, dialect, decl=PERMISSIVE)) == ([], 0, 0)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT id FROM people WHERE full_name <> city", OP),
        ("SELECT id FROM people WHERE full_name <> 'tk_abcdefghijklmnop'", OP),
        ("SELECT id FROM people WHERE full_name NOT IN ('Ivan Petrov')", OP),
        ("SELECT id FROM people WHERE full_name <> 5", Reason.LITERAL_TYPE_MISMATCH),
    ],
)
def test_refused_even_in_permissive(
    policy: PolicyRun, sql: str, reason: Reason, dialect: str
) -> None:
    assert policy(sql, dialect, decl=PERMISSIVE) == reason


@pytest.mark.parametrize("dialect", DIALECTS)
def test_ne_binds_and_passes_the_recheck(prepare_sql: PrepareRun, dialect: str) -> None:
    prepared = prepare_sql("SELECT id FROM people WHERE full_name <> 'Zq One'", dialect, PERMISSIVE)
    assert "Zq One" in prepared.params.values()
