"""The order of identifier values: sorting, MIN / MAX and ordering probes, in permissive."""

import pytest

from incognito_sql.core.errors import Reason

from .conftest import DECL, DIALECTS, PolicyRun, PrepareRun, summary

PERMISSIVE = DECL.model_copy(update={"protection": "permissive"})
BALANCED = DECL.model_copy(update={"protection": "balanced"})
OP = Reason.PII_OPERATION


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    ("sql", "outcome"),
    [
        ("SELECT id FROM people ORDER BY full_name", ([], 0, 0)),
        ("SELECT full_name FROM people ORDER BY 1", ([0], 0, 0)),
        ("SELECT min(full_name), max(phone) FROM people", ([0, 1], 0, 0)),
        ("SELECT id FROM people WHERE full_name > 'Ivan'", ([], 0, 0)),
        ("SELECT id FROM people WHERE phone BETWEEN 5550000 AND 5559999", ([], 0, 0)),
        ("SELECT p.id FROM people p JOIN orders o ON p.full_name < o.customer_name", ([], 0, 0)),
    ],
)
def test_order_is_permissive_only(
    policy: PolicyRun, sql: str, outcome: object, dialect: str
) -> None:
    assert policy(sql, dialect) == OP
    assert policy(sql, dialect, decl=BALANCED) == OP
    assert summary(policy(sql, dialect, decl=PERMISSIVE)) == outcome


@pytest.mark.parametrize("dialect", DIALECTS)
def test_probe_literals_are_counted(policy: PolicyRun, dialect: str) -> None:
    result = policy(
        "SELECT id FROM people WHERE phone BETWEEN 5550000 AND 5559999", dialect, decl=PERMISSIVE
    )
    assert not isinstance(result, Reason)
    assert len(result.probe_literals) == 2


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT id FROM people WHERE full_name > city", OP),
        ("SELECT id FROM people WHERE full_name > 'tk_abcdefghijklmnop'", OP),
        ("SELECT id FROM people WHERE full_name > upper('x')", OP),
        ("SELECT id FROM people WHERE NOT full_name > 'A'", OP),
        ("SELECT full_name > 'A' FROM people", OP),
        ("SELECT id FROM people WHERE full_name > 5", Reason.LITERAL_TYPE_MISMATCH),
        ("SELECT id FROM people WHERE phone > 'x'", Reason.LITERAL_TYPE_MISMATCH),
    ],
)
def test_refused_even_in_permissive(
    policy: PolicyRun, sql: str, reason: Reason, dialect: str
) -> None:
    assert policy(sql, dialect, decl=PERMISSIVE) == reason


@pytest.mark.parametrize("dialect", DIALECTS)
def test_a_probe_binds_its_literal_and_passes_the_recheck(
    prepare_sql: PrepareRun, dialect: str
) -> None:
    prepared = prepare_sql(
        "SELECT min(full_name) FROM people WHERE full_name > 'Ivan' ORDER BY 1", dialect, PERMISSIVE
    )
    assert "Ivan" not in prepared.sql
    assert "Ivan" in prepared.params.values()
    assert [str(c) for c in prepared.output_classes] == ["identifier"]
