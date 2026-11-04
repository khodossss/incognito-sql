"""SQLite reads a double-quoted name that names nothing as a string."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import PolicyRun, summary


@pytest.mark.parametrize(
    ("sql", "outcome"),
    [
        ('SELECT id FROM people WHERE city = "Zqtown"', ([], 0, 0)),
        ('SELECT id FROM people WHERE full_name = "Ivan Petrov"', ([], 1, 0)),
        ('SELECT id FROM people WHERE full_name = "Zq Unknown" OR city = "x y"', ([], 1, 0)),
        ('SELECT id FROM people WHERE city = "city"', ([], 0, 0)),
        ('SELECT id AS "label" FROM people WHERE city = "label"', ([], 0, 0)),  # an alias
        ('SELECT id FROM people WHERE p.city = "Zqtown"', Reason.UNKNOWN_COLUMN),
    ],
)
def test_sqlite_double_quoted_strings(policy: PolicyRun, sql: str, outcome: object) -> None:
    assert summary(policy(sql, "sqlite")) == outcome


def test_other_dialects_keep_quoted_names(policy: PolicyRun) -> None:
    assert policy('SELECT id FROM people WHERE city = "Zqtown"', "postgres") == (
        Reason.UNKNOWN_COLUMN
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM people WHERE city = [Zqtown]",
        "SELECT id FROM people WHERE city = `Zqtown`",
        "SELECT [id; DROP TABLE x] FROM people",
        'SELECT "rowid" FROM people',
    ],
)
def test_only_double_quotes_become_strings(policy: PolicyRun, sql: str) -> None:
    assert policy(sql, "sqlite") == Reason.UNKNOWN_COLUMN
