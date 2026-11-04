"""MIN / MAX of an identifier carries the value: its own place is checked like the column."""

import pytest
from sqlglot.optimizer.qualify import qualify

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.lineage import Lineage
from incognito_sql.core.sql.parse import parse
from incognito_sql.core.sql.policy_places import check_places

from .conftest import CATALOG, DECL, DIALECTS, SCHEMA, PolicyRun, summary

PERMISSIVE = DECL.model_copy(update={"protection": "permissive"})
OP = Reason.PII_OPERATION


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        (
            "SELECT id FROM people GROUP BY id HAVING substr(max(full_name), 1, 1) = 'Z'",
            OP,
        ),
        ("SELECT upper(min(full_name)) FROM people", OP),
        ("SELECT max(full_name) > 'M' FROM people", OP),
        (
            "SELECT count(*) FROM orders HAVING max(customer_name) = max(note)",
            Reason.PII_JOIN_WITH_OPEN,
        ),
        ("SELECT count(*) FROM orders HAVING max(customer_name) > max(note)", OP),
        ("SELECT count(*) FROM orders HAVING max(customer_name) LIKE max(note)", OP),
    ],
)
def test_an_aggregate_of_an_identifier_is_refused_where_the_column_is(
    policy: PolicyRun, sql: str, reason: Reason, dialect: str
) -> None:
    assert policy(sql, dialect, decl=PERMISSIVE) == reason


@pytest.mark.parametrize("dialect", DIALECTS)
def test_an_aggregate_compared_with_a_literal_spends_the_budget(
    policy: PolicyRun, dialect: str
) -> None:
    eq = policy(
        "SELECT count(*) FROM people HAVING max(full_name) = 'Ivan Petrov'",
        dialect,
        decl=PERMISSIVE,
    )
    assert summary(eq) == ([], 1, 0)
    probe = policy(
        "SELECT count(*) FROM people HAVING max(full_name) LIKE 'I%'", dialect, decl=PERMISSIVE
    )
    assert not isinstance(probe, Reason)
    assert len(probe.probe_literals) == 1
    assert (
        policy("SELECT count(*) FROM people HAVING max(full_name) = 'Ivan Petrov'", dialect) == OP
    )


def test_an_ordered_aggregate_may_return_its_sort_key() -> None:
    # The allowlist and the grouping check refuse it first; the place is refused on its own.
    sql = "SELECT percentile_disc(0.5) WITHIN GROUP (ORDER BY full_name) FROM people"
    tree = qualify(parse(sql, "postgres", Limits()), schema=SCHEMA, dialect="postgres")
    with pytest.raises(Rejection) as exc:
        check_places(tree, Lineage(tree, CATALOG, PERMISSIVE), lambda _ref, _op: True)
    assert exc.value.reason is OP
