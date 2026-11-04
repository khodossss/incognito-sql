"""LIKE over an identifier: prefix and contains probes, in permissive."""

import pytest

from incognito_sql.core.config import Operation
from incognito_sql.core.config.protection import CustomProfile
from incognito_sql.core.errors import Reason

from .conftest import DECL, DIALECTS, PolicyRun, PrepareRun, summary

PERMISSIVE = DECL.model_copy(update={"protection": "permissive"})
PREFIX_ONLY = DECL.model_copy(
    update={
        "protections": {"lean": CustomProfile(extends="permissive", deny=[Operation.CONTAINS])},
        "protection": "lean",
    }
)
OP = Reason.PII_OPERATION
PREFIXES = [
    "SELECT id FROM people WHERE full_name LIKE 'Iv%'",
    "SELECT id FROM people WHERE full_name NOT LIKE 'Iv%'",
    "SELECT id FROM people WHERE full_name ILIKE 'iv%'",
]
CONTAINS = [
    "SELECT id FROM people WHERE full_name LIKE '%van%'",
    "SELECT id FROM people WHERE full_name LIKE 'I_an%'",
    "SELECT id FROM people WHERE full_name LIKE '%'",
]


@pytest.mark.parametrize("dialect", ["postgres"])
@pytest.mark.parametrize("sql", PREFIXES + CONTAINS)
def test_like_is_permissive_only(policy: PolicyRun, sql: str, dialect: str) -> None:
    assert policy(sql, dialect) == OP
    result = policy(sql, dialect, decl=PERMISSIVE)
    assert summary(result) == ([], 0, 0)
    assert not isinstance(result, Reason)
    assert len(result.probe_literals) == 1


@pytest.mark.parametrize("sql", ["SELECT id FROM people WHERE full_name LIKE 'Iv%'"])
@pytest.mark.parametrize("dialect", DIALECTS)
def test_like_on_every_dialect(policy: PolicyRun, sql: str, dialect: str) -> None:
    assert summary(policy(sql, dialect, decl=PERMISSIVE)) == ([], 0, 0)


@pytest.mark.parametrize("dialect", ["postgres"])
def test_prefix_and_contains_are_apart(policy: PolicyRun, dialect: str) -> None:
    assert summary(policy(PREFIXES[0], dialect, decl=PREFIX_ONLY)) == ([], 0, 0)
    assert policy(CONTAINS[0], dialect, decl=PREFIX_ONLY) == OP


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM people WHERE full_name LIKE city",
        "SELECT id FROM people WHERE 'Ivan Petrov' LIKE full_name",
        "SELECT id FROM people WHERE full_name LIKE 'tk_abcdefghijklmnop'",
        "SELECT id FROM people WHERE NOT (full_name LIKE 'I%')",
        "SELECT full_name LIKE 'I%' FROM people",
        "SELECT id FROM people WHERE upper(full_name) LIKE 'I%'",
    ],
)
def test_refused_even_in_permissive(policy: PolicyRun, sql: str, dialect: str) -> None:
    assert policy(sql, dialect, decl=PERMISSIVE) in {OP, Reason.NODE_NOT_ALLOWED}


@pytest.mark.parametrize("dialect", DIALECTS)
def test_a_pattern_binds_and_passes_the_recheck(prepare_sql: PrepareRun, dialect: str) -> None:
    prepared = prepare_sql("SELECT id FROM people WHERE full_name LIKE 'Zq%'", dialect, PERMISSIVE)
    assert "Zq%" not in prepared.sql
    assert "Zq%" in prepared.params.values()
