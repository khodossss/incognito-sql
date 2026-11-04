"""Window functions: only where the profile admits the form, never over an identifier."""

import pytest

from incognito_sql.core.config import Operation
from incognito_sql.core.config.protection import CustomProfile
from incognito_sql.core.errors import Reason

from .conftest import DECL, DIALECTS, PolicyRun, PrepareRun, summary

PERMISSIVE = DECL.model_copy(update={"protection": "permissive"})
BALANCED = DECL.model_copy(update={"protection": "balanced"})
NNA = Reason.NODE_NOT_ALLOWED

OPEN = [
    "SELECT id, ROW_NUMBER() OVER (PARTITION BY city ORDER BY id DESC) FROM people",
    "SELECT id, RANK() OVER (ORDER BY city), DENSE_RANK() OVER (ORDER BY city) FROM people",
    "SELECT p.city, SUM(o.amount) OVER (PARTITION BY p.city) FROM people p JOIN orders o ON 1=1",
    "SELECT id, COUNT(*) OVER () FROM people",
    (
        "SELECT id, AVG(amount) OVER (ORDER BY id ROWS BETWEEN 1 PRECEDING AND CURRENT ROW)"
        " FROM orders"
    ),
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("sql", OPEN)
def test_windows_are_permissive_only(policy: PolicyRun, sql: str, dialect: str) -> None:
    assert policy(sql, dialect) == NNA
    assert policy(sql, dialect, decl=BALANCED) == NNA
    assert summary(policy(sql, dialect, decl=PERMISSIVE)) == ([], 0, 0)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT id, COUNT(*) OVER (PARTITION BY phone) FROM people", Reason.PII_OPERATION),
        ("SELECT LAG(city) OVER (ORDER BY id) FROM people", NNA),
        (
            (
                "SELECT AVG(amount) OVER (ORDER BY id ROWS BETWEEN (SELECT 1) PRECEDING"
                " AND CURRENT ROW) FROM orders"
            ),
            NNA,
        ),
    ],
)
def test_refused_even_in_permissive(
    policy: PolicyRun, sql: str, reason: Reason, dialect: str
) -> None:
    assert policy(sql, dialect, decl=PERMISSIVE) == reason


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT p.city, SUM(p.id) OVER (PARTITION BY p.city) FROM people p GROUP BY p.city",
        "SELECT p.city, RANK() OVER (ORDER BY p.id) FROM people p GROUP BY p.city",
        "SELECT p.city, COUNT(*) OVER (PARTITION BY p.id) FROM people p GROUP BY p.city",
    ],
)
def test_a_window_in_a_grouped_select_reads_only_grouped_values(
    policy: PolicyRun, sql: str, dialect: str
) -> None:
    assert policy(sql, dialect, decl=PERMISSIVE) == NNA


@pytest.mark.parametrize("dialect", DIALECTS)
def test_a_window_over_aggregates_of_the_group(policy: PolicyRun, dialect: str) -> None:
    sql = "SELECT p.city, RANK() OVER (ORDER BY COUNT(*)) FROM people p GROUP BY p.city"
    assert summary(policy(sql, dialect, decl=PERMISSIVE)) == ([], 0, 0)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_a_window_ordered_by_an_identifier_is_the_order_operation(
    policy: PolicyRun, dialect: str
) -> None:
    sql = "SELECT ROW_NUMBER() OVER (ORDER BY full_name) FROM people"
    assert summary(policy(sql, dialect, decl=PERMISSIVE)) == ([], 0, 0)
    no_order = DECL.model_copy(
        update={
            "protections": {"lean": CustomProfile(extends="permissive", deny=[Operation.ORDER])},
            "protection": "lean",
        }
    )
    assert policy(sql, dialect, decl=no_order) == Reason.PII_OPERATION


@pytest.mark.parametrize("dialect", DIALECTS)
def test_window_keys_do_not_flow_into_its_value(prepare_sql: PrepareRun, dialect: str) -> None:
    sql = "SELECT COUNT(*) OVER (PARTITION BY city ORDER BY id) FROM people"
    prepared = prepare_sql(sql, dialect, PERMISSIVE)
    assert [str(c) for c in prepared.output_classes] == ["open"]


WINDOW = "SELECT id, COUNT(*) OVER (ORDER BY {} {}) FROM people"
DISTANCE = [
    "RANGE BETWEEN 95 PRECEDING AND CURRENT ROW",
    "RANGE BETWEEN CURRENT ROW AND 5 FOLLOWING",
]
POSITION = [
    "RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW",
    "ROWS BETWEEN 2 PRECEDING AND CURRENT ROW",
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("frame", DISTANCE)
def test_a_range_offset_over_an_identifier_key_measures_distance(
    policy: PolicyRun, frame: str, dialect: str
) -> None:
    assert policy(WINDOW.format("phone", frame), dialect, decl=PERMISSIVE) == Reason.PII_OPERATION
    assert summary(policy(WINDOW.format("id", frame), dialect, decl=PERMISSIVE)) == ([], 0, 0)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("frame", POSITION)
def test_a_frame_without_distance_keeps_the_order_operation(
    policy: PolicyRun, frame: str, dialect: str
) -> None:
    assert summary(policy(WINDOW.format("phone", frame), dialect, decl=PERMISSIVE)) == ([], 0, 0)
