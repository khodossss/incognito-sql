"""A projection alias may not repeat a name its SELECT sees, stars and derived tables included."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import DIALECTS, Outcome, PolicyRun, summary

AMB = Reason.AMBIGUOUS_COLUMN
OK: Outcome = ([], 0, 0)

CASES: list[tuple[str, Outcome]] = [
    # every SELECT is checked, also after a set operation and after a star
    (
        (
            "SELECT p.city AS full_name FROM (SELECT id FROM people UNION SELECT id FROM orders) d"
            " JOIN people p ON p.id = d.id"
        ),
        AMB,
    ),
    ("SELECT p.*, p.city AS full_name FROM people p", AMB),
    # names a derived table outputs: its own aliases and what its stars expand to
    ("SELECT d.id AS f FROM (SELECT id, city AS f FROM people) d", AMB),
    ("SELECT d.id AS full_name FROM (SELECT * FROM people) d", AMB),
    ("SELECT d.city AS f FROM (SELECT id AS f, * FROM people) d", AMB),
    # a star is not a name, and `t.*` carries only the columns of `t`
    ("SELECT CAST(count(*) AS TEXT) FROM (SELECT * FROM people) d", OK),
    ("SELECT d.id AS note FROM (SELECT p.* FROM people p JOIN orders o ON o.id = p.id) d", OK),
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "expected"), CASES)
def test_alias_shadowing(policy: PolicyRun, dialect: str, sql: str, expected: Outcome) -> None:
    assert summary(policy(sql, dialect)) == expected
