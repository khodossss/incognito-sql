"""INTERSECT and EXCEPT: the union rules, and a join of identifiers under the profile."""

import pytest

from incognito_sql.core.config import Operation
from incognito_sql.core.config.protection import CustomProfile
from incognito_sql.core.errors import Reason

from .conftest import DECL, DIALECTS, PolicyRun, summary

NO_JOIN = DECL.model_copy(
    update={
        "protections": {"solo": CustomProfile(extends="strict", deny=[Operation.JOIN_IDENT])},
        "column_protection": {"orders": {"customer_name": "solo"}},
    }
)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("op", ["INTERSECT", "EXCEPT"])
@pytest.mark.parametrize(
    ("sql", "outcome"),
    [
        ("SELECT city FROM people {op} SELECT note FROM orders", ([], 0, 0)),
        ("SELECT full_name FROM people {op} SELECT customer_name FROM orders", ([0], 0, 0)),
        ("SELECT full_name FROM people {op} SELECT note FROM orders", Reason.PII_JOIN_WITH_OPEN),
        ("SELECT full_name FROM people {op} SELECT 'Ivan Petrov'", Reason.PII_JOIN_WITH_OPEN),
        ("SELECT notes FROM people {op} SELECT note FROM orders", Reason.HIDDEN_COLUMN),
    ],
)
def test_set_operations_follow_the_union_rules(
    policy: PolicyRun, sql: str, op: str, outcome: object, dialect: str
) -> None:
    assert summary(policy(sql.format(op=op), dialect)) == outcome


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("op", ["INTERSECT", "EXCEPT"])
def test_matching_identifiers_needs_join_ident(policy: PolicyRun, op: str, dialect: str) -> None:
    sql = f"SELECT full_name FROM people {op} SELECT customer_name FROM orders"  # noqa: S608
    assert policy(sql, dialect, decl=NO_JOIN) == Reason.PII_OPERATION
    union = "SELECT full_name FROM people UNION SELECT customer_name FROM orders"
    assert summary(policy(union, dialect, decl=NO_JOIN)) == ([0], 0, 0)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("op", ["UNION", "INTERSECT", "EXCEPT"])
def test_branches_may_reuse_aliases(policy: PolicyRun, op: str, dialect: str) -> None:
    branch = "SELECT t1.city FROM people AS t1 JOIN orders AS t2 ON t1.id = t2.id"
    sql = f"{branch} WHERE t2.amount > 1 {op} {branch}"
    assert summary(policy(sql, dialect)) == ([], 0, 0)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT t.id FROM people AS t JOIN orders AS t ON t.id = t.id",
        "SELECT p.id FROM people AS p WHERE p.id IN (SELECT p.id FROM orders AS p)",
        "SELECT p.id FROM people AS p UNION SELECT p.id FROM people AS p JOIN orders AS p ON 1=1",
    ],
)
def test_aliases_still_unique_within_a_branch(policy: PolicyRun, sql: str, dialect: str) -> None:
    assert policy(sql, dialect) == Reason.AMBIGUOUS_COLUMN
