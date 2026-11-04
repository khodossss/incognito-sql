"""What a compared literal or token costs: model items against limits, at most 16 forms each."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, event

from incognito_sql.core.config import Limits
from incognito_sql.core.db import make_engine
from incognito_sql.core.display import DisplayIds
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.sql.catalog import reflect
from incognito_sql.core.tokens.store import TokenStore

from .conftest import DECL, NOW, PrepareRun

MAX_FORMS = 16  # K: forms bound per model item
FORMS = ["Ivan Petrov" + " " * n for n in range(24)]  # 24 spellings of one value


def test_in_limit_counts_what_the_model_wrote(store: TokenStore, prepare_sql: PrepareRun) -> None:
    tok = store.tokenize("Ivan Petrov", NOW)
    store.tokenize("ivan petrov ", NOW)
    store.tokenize("Zq Other", NOW)
    store.tokenize("ZQ OTHER", NOW)
    decl = DECL.model_copy(update={"limits": Limits(max_in_items=2)})
    p = prepare_sql(f"SELECT id FROM people WHERE full_name IN ('{tok}', 'zq other')", decl=decl)  # noqa: S608
    assert len(p.params) == 5


def test_a_token_binds_at_most_k_forms_earliest_first(
    store: TokenStore, prepare_sql: PrepareRun
) -> None:
    tok = store.tokenize(FORMS[0], NOW)
    for form in FORMS[1:]:
        store.tokenize(form, NOW)
    assert len(store.variants(tok, NOW)) == len(FORMS)
    p = prepare_sql(f"SELECT id FROM people WHERE full_name = '{tok}'")  # noqa: S608
    assert list(p.params.values()) == FORMS[:MAX_FORMS]


def test_a_literal_binds_itself_and_at_most_k_forms(
    store: TokenStore, prepare_sql: PrepareRun
) -> None:
    for form in FORMS:
        store.tokenize(form, NOW)
    p = prepare_sql("SELECT id FROM people WHERE full_name = 'IVAN PETROV'")
    assert list(p.params.values()) == ["IVAN PETROV", *FORMS[: MAX_FORMS - 1]]


def _in(start: int, count: int) -> str:
    return "full_name IN (" + ", ".join(f"'Zz{i}'" for i in range(start, start + count)) + ")"


@pytest.mark.parametrize(("dialect", "refused"), [("tsql", True), ("postgres", False)])
def test_too_many_items_for_the_dialect_refused_by_shape(
    prepare_sql: PrepareRun, dialect: str, *, refused: bool
) -> None:
    # 135 items x 16 forms is over SQL Server's 2100 parameters, whatever is stored.
    where = " OR ".join(_in(start, 45) for start in (0, 45, 90))
    sql = f"SELECT id FROM people WHERE {where}"  # noqa: S608
    if not refused:
        assert len(prepare_sql(sql, dialect).params) == 135
        return
    with pytest.raises(Rejection) as exc:
        prepare_sql(sql, dialect)
    assert exc.value.reason is Reason.LIMIT_EXCEEDED


@pytest.mark.parametrize(("others", "refused"), [(5, False), (6, True)])
def test_parameter_budget_boundary(prepare_sql: PrepareRun, others: int, *, refused: bool) -> None:
    # SQLite takes 999: 62 compared items x 16 forms + 5 other values + 2 (a constant false).
    compared = " OR ".join(_in(start, 31) for start in (0, 31))
    listed = ", ".join(str(n) for n in range(others))
    sql = f"SELECT id FROM people WHERE ({compared}) AND id IN ({listed})"  # noqa: S608
    if not refused:
        assert len(prepare_sql(sql, "sqlite").params) == 62 + others
        return
    with pytest.raises(Rejection) as exc:
        prepare_sql(sql, "sqlite")
    assert exc.value.reason is Reason.LIMIT_EXCEEDED


def test_an_equality_is_one_item(prepare_sql: PrepareRun) -> None:
    decl = DECL.model_copy(update={"limits": Limits(max_in_items=1)})
    p = prepare_sql("SELECT id FROM people WHERE full_name = 'Zq One'", decl=decl)
    assert list(p.params.values()) == ["Zq One"]


@pytest.fixture
def people_engine(people_db: Path) -> Iterator[Engine]:
    engine = make_engine(f"sqlite:///{people_db}", "sqlite")
    yield engine
    engine.dispose()


def test_entity_lookup_binds_at_most_k_forms(people_engine: Engine, store: TokenStore) -> None:
    for form in FORMS:
        store.tokenize(form, NOW)
    seen: list[int] = []

    def count(*args: object) -> None:
        params = args[3]
        seen.append(len(params) if isinstance(params, tuple | list | dict) else 0)

    event.listen(people_engine, "before_cursor_execute", count)
    decl = DECL.model_copy(update={"dialect": "sqlite"})
    ids = DisplayIds(decl, reflect(people_engine, "sqlite"), store, people_engine)
    assert ids.find("Ivan Petrov") == {"people": [1]}
    assert seen
    assert max(seen) <= MAX_FORMS
