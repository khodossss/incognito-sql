"""The re-check of rewritten SQL: no value, no comment, binds exactly the parameters."""

import pytest

from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.recheck import recheck

from .conftest import CATALOG, DECL, PrepareRun

CLEAN = "SELECT people.id AS id FROM people WHERE people.id = :p0"


def test_rewritten_shape_passes() -> None:
    recheck(CLEAN, {"p0": 1}, CATALOG, DECL)


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        (f"{CLEAN} -- note", {"p0": 1}),
        (f"{CLEAN} /* note */", {"p0": 1}),
        ("SELECT people.id AS id FROM people WHERE people.id = 1", {}),
        (CLEAN, {"p0": 1, "p1": 2}),  # a parameter the SQL does not bind
        (CLEAN, {}),
    ],
)
def test_leftovers_are_refused(sql: str, params: dict[str, object]) -> None:
    with pytest.raises(Rejection) as exc:
        recheck(sql, params, CATALOG, DECL)
    assert exc.value.reason is Reason.NODE_NOT_ALLOWED


@pytest.mark.parametrize(("dialect", "db"), [("postgres", "public"), ("sqlite", "main")])
def test_default_schema_survives_the_recheck(
    prepare_sql: PrepareRun, dialect: str, db: str
) -> None:
    p = prepare_sql(f"SELECT full_name FROM {db}.people", dialect)  # noqa: S608
    assert f"FROM {db}.people" in p.sql
