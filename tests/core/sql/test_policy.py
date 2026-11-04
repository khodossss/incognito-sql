"""The case table of the default-deny policy for personal columns."""

import pytest

from incognito_sql.core.errors import Reason
from incognito_sql.core.sql.policy import PolicyResult

from .conftest import DIALECTS, Outcome, PolicyRun, summary

IN_51 = ", ".join(f"'Zq{i}'" for i in range(51))


CASES: list[tuple[str, Outcome]] = [
    ("SELECT full_name, city FROM people WHERE full_name = 'Ivan Petrov'", ([0], 1, 0)),
    ("SELECT city, count(*) FROM people GROUP BY full_name, city", ([], 0, 0)),
    ("SELECT p.id FROM people p JOIN orders o ON o.customer_name = p.full_name", ([], 0, 0)),
    ("SELECT p.id FROM people p JOIN orders o ON o.note = p.full_name", Reason.PII_JOIN_WITH_OPEN),
    ("SELECT upper(full_name) FROM people", Reason.PII_OPERATION),
    ("SELECT id FROM people WHERE full_name LIKE 'I%'", Reason.PII_OPERATION),
    ("SELECT full_name AS n FROM people ORDER BY n", Reason.PII_OPERATION),
    ("SELECT full_name AS n FROM people ORDER BY 1", Reason.PII_OPERATION),
    ("SELECT min(full_name) FROM people", Reason.PII_OPERATION),
    ("SELECT p FROM people p", Reason.UNKNOWN_COLUMN),
    ("SELECT row_to_json(p) FROM people p", Reason.NODE_NOT_ALLOWED),
    ("SELECT notes FROM people", Reason.HIDDEN_COLUMN),
    ("SELECT id FROM people WHERE notes = 'x'", Reason.HIDDEN_COLUMN),
    ("SELECT * FROM pg_stats", Reason.SYSTEM_CATALOG),
    ("SELECT * FROM information_schema.columns", Reason.SYSTEM_CATALOG),
    ("SELECT full_n\N{CYRILLIC SMALL LETTER A}me FROM people", Reason.UNKNOWN_COLUMN),
    ("SELECT id FROM people WHERE phone = 'abc'", Reason.LITERAL_TYPE_MISMATCH),
    (f"SELECT id FROM people WHERE full_name IN ({IN_51})", Reason.LIMIT_EXCEEDED),  # noqa: S608
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "expected"), CASES)
def test_case_table(policy: PolicyRun, dialect: str, sql: str, expected: Outcome) -> None:
    assert summary(policy(sql, dialect)) == expected


@pytest.mark.parametrize("dialect", DIALECTS)
def test_window_over_identifier(policy: PolicyRun, dialect: str) -> None:
    sql = "SELECT row_number() OVER (ORDER BY full_name) FROM people"
    # Windows are a form of the permissive profile only; under strict the policy closes
    # them before it looks at the identifier.
    assert policy(sql, dialect) == Reason.NODE_NOT_ALLOWED
    assert policy(sql, dialect, nodes=False) == Reason.NODE_NOT_ALLOWED


@pytest.mark.parametrize("dialect", DIALECTS)
def test_literal_is_the_compared_node(policy: PolicyRun, dialect: str) -> None:
    result = policy("SELECT id FROM people WHERE full_name = 'Ivan Petrov'", dialect)
    assert isinstance(result, PolicyResult)
    assert [lit.this for lit in result.pii_literals] == ["Ivan Petrov"]
