"""SQLite's date and position functions over open columns; nothing else by name."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import Outcome, PolicyRun, summary

OK: Outcome = ([], 0, 0)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT strftime('%Y', city) FROM people",
        "SELECT date(city), julianday(city), datetime(city, '+1 day'), time(city) FROM people",
        "SELECT id FROM people WHERE instr(city, 'z') > 0",
        "SELECT id FROM people WHERE date(city) > date('now')",
    ],
)
def test_on_open_columns(policy: PolicyRun, sql: str) -> None:
    assert summary(policy(sql, "sqlite")) == OK


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT strftime('%Y', full_name) FROM people", Reason.PII_OPERATION),
        ("SELECT id FROM people WHERE instr(full_name, 'I') > 0", Reason.PII_OPERATION),
        ("SELECT julianday(phone) FROM people", Reason.PII_OPERATION),
        ("SELECT load_extension(city) FROM people", Reason.NODE_NOT_ALLOWED),
        ("SELECT unixepoch(city) FROM people", Reason.NODE_NOT_ALLOWED),
    ],
)
def test_refused(policy: PolicyRun, sql: str, reason: Reason) -> None:
    assert policy(sql, "sqlite") == reason
