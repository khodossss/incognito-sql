"""The protection profile of a column decides which operations reach it."""

import pytest

from incognito_sql.core.config import Declaration, Operation
from incognito_sql.core.config.protection import CustomProfile
from incognito_sql.core.errors import Reason

from .conftest import DECL, DIALECTS, PolicyRun, summary

OP = Reason.PII_OPERATION


def _with(**update: object) -> Declaration:
    return DECL.model_copy(update=update)


PERMISSIVE = _with(protection="permissive")
NO_LITERALS = _with(
    protections={"lean": CustomProfile(extends="balanced", deny=[Operation.EQ_LITERAL])},
    protection="lean",
)
PHONE_STRICT_ONLY = _with(
    protections={
        "bare": CustomProfile(extends="strict", deny=[Operation.JOIN_IDENT, Operation.OUTPUT])
    },
    column_protection={"people": {"phone": "bare"}},
)

NULL_TESTS = [
    "SELECT id FROM people WHERE full_name IS NULL",
    "SELECT id FROM people WHERE full_name IS NOT NULL AND id = 1",
    "SELECT people.id FROM people JOIN orders ON orders.customer_name IS NULL",
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("sql", NULL_TESTS)
def test_null_test_needs_a_profile_that_admits_it(
    policy: PolicyRun, sql: str, dialect: str
) -> None:
    assert policy(sql, dialect) == OP
    assert summary(policy(sql, dialect, decl=PERMISSIVE)) == ([], 0, 0)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT full_name IS NULL FROM people", OP),
        ("SELECT id FROM people WHERE (full_name IS NULL) = (1 = 1)", OP),
        ("SELECT id FROM people WHERE NULL IS full_name", OP),
        (
            "SELECT id FROM people WHERE full_name IS NOT DISTINCT FROM 'Ivan Petrov'",
            Reason.NODE_NOT_ALLOWED,
        ),
    ],
)
def test_null_test_outside_a_condition_is_refused(
    policy: PolicyRun, sql: str, reason: Reason, dialect: str
) -> None:
    assert policy(sql, dialect, decl=PERMISSIVE) == reason


@pytest.mark.parametrize("dialect", DIALECTS)
def test_denied_literal_comparison_is_refused(policy: PolicyRun, dialect: str) -> None:
    sql = "SELECT id FROM people WHERE full_name = 'Ivan Petrov'"
    assert summary(policy(sql, dialect)) == ([], 1, 0)
    assert policy(sql, dialect, decl=NO_LITERALS) == OP
    keyed = "SELECT id FROM people WHERE full_name = 'tk_abcdefghijklmnop'"
    assert summary(policy(keyed, dialect, decl=NO_LITERALS)) == ([], 0, 1)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_column_profile_binds_only_its_column(policy: PolicyRun, dialect: str) -> None:
    assert policy("SELECT phone FROM people", dialect, decl=PHONE_STRICT_ONLY) == OP
    assert summary(policy("SELECT full_name FROM people", dialect, decl=PHONE_STRICT_ONLY)) == (
        [0],
        0,
        0,
    )
    group = "SELECT count(*) FROM people GROUP BY phone"
    assert summary(policy(group, dialect, decl=PHONE_STRICT_ONLY)) == ([], 0, 0)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_join_of_two_identifiers_checks_both_profiles(policy: PolicyRun, dialect: str) -> None:
    sql = "SELECT o.id FROM orders o JOIN people p ON p.full_name = o.customer_name"
    assert summary(policy(sql, dialect)) == ([], 0, 0)
    no_join = _with(
        protections={"solo": CustomProfile(extends="balanced", deny=[Operation.JOIN_IDENT])},
        column_protection={"orders": {"customer_name": "solo"}},
    )
    assert policy(sql, dialect, decl=no_join) == OP


NAME_NO_LITERALS = _with(
    protections={"bare": CustomProfile(extends="permissive", deny=[Operation.EQ_LITERAL])},
    column_protection={"orders": {"customer_name": "bare"}},
)
UNIONS = [
    "SELECT full_name AS v FROM people UNION ALL SELECT customer_name FROM orders",
    "SELECT customer_name AS v FROM orders UNION ALL SELECT full_name FROM people",
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("union", UNIONS)
def test_every_branch_of_a_union_answers_for_its_profile(
    policy: PolicyRun, union: str, dialect: str
) -> None:
    through_cte = f"WITH u AS ({union}) SELECT 1 FROM u WHERE v = 'Ivan Petrov'"  # noqa: S608
    assert policy(through_cte, dialect, decl=NAME_NO_LITERALS) == OP
    through_in = f"SELECT 1 FROM people WHERE 'Ivan Petrov' IN ({union})"  # noqa: S608
    assert policy(through_in, dialect, decl=NAME_NO_LITERALS) == OP
    null_test = f"WITH u AS ({union}) SELECT 1 FROM u WHERE v IS NULL"  # noqa: S608
    assert summary(policy(null_test, dialect, decl=PERMISSIVE)) == ([], 0, 0)
    held = _with(protection="permissive", column_protection={"orders": {"customer_name": "strict"}})
    assert policy(null_test, dialect, decl=held) == OP


@pytest.mark.parametrize("dialect", DIALECTS)
def test_count_of_an_identifier_is_a_null_test(policy: PolicyRun, dialect: str) -> None:
    sql = "SELECT count(full_name) FROM people"
    assert policy(sql, dialect) == OP
    assert summary(policy(sql, dialect, decl=_with(protection="balanced"))) == ([], 0, 0)
