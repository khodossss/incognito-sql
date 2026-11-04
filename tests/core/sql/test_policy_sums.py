"""SUM / AVG over a CASE of small integers everywhere; over other expressions in permissive."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import DECL, DIALECTS, Outcome, PolicyRun, summary

PERMISSIVE = DECL.model_copy(update={"protection": "permissive"})
OK: Outcome = ([], 0, 0)
NNA = Reason.NODE_NOT_ALLOWED


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(CASE WHEN city = 'Zqtown' THEN 1 ELSE 0 END) FROM people",
        "SELECT AVG(CASE WHEN o.amount > 5 THEN 1 END) FROM orders o",
        "SELECT SUM(CASE WHEN id = 1 THEN 2 WHEN id = 2 THEN (3) ELSE NULL END) FROM people",
    ],
)
def test_bounded_case_sums_everywhere(policy: PolicyRun, sql: str, dialect: str) -> None:
    assert summary(policy(sql, dialect)) == OK


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(CASE WHEN id = 1 THEN 1.5 ELSE 0 END) FROM people",
        "SELECT SUM(CASE WHEN id = 1 THEN -1000000 ELSE 1000000 END) FROM people",
        "SELECT SUM(CASE WHEN id = 1 THEN 10000000 ELSE 0 END) FROM people",
        "SELECT SUM(CASE WHEN id = 1 THEN id ELSE 0 END) FROM people",
        "SELECT SUM(amount * 2) FROM orders",
    ],
)
def test_other_computed_sums_are_permissive_only(policy: PolicyRun, sql: str, dialect: str) -> None:
    assert policy(sql, dialect) == NNA
    assert summary(policy(sql, dialect, decl=PERMISSIVE)) == OK


@pytest.mark.parametrize("dialect", DIALECTS)
def test_a_sum_over_an_identifier_stays_refused(policy: PolicyRun, dialect: str) -> None:
    sql = "SELECT SUM(phone + 0) FROM people"
    assert policy(sql, dialect, decl=PERMISSIVE) == Reason.PII_OPERATION
