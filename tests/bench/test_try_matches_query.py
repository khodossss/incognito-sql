"""`try` judges the corpus as the server does: the same refusal, or an answer it gives.

Under each output mode and protection profile: a wider profile opens query forms, the
likeliest place for the two to part.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from bench.cases import load_cases
from bench.harness import Run, open_runs
from bench.templates import expand
from bench.world import World
from incognito_sql.core.config import load_declaration
from incognito_sql.core.db import make_engine
from incognito_sql.core.sql.catalog import Catalog, reflect
from incognito_sql.trial.verdict import PSEUDONYM, VALUE, Verdict, verdict

PROFILES = ("balanced", "permissive")
RUNS = ("web", "labels", *PROFILES)
LINK = "/v/tk_"  # a value link: the cell is a pseudonym


def _differs(tried: tuple[str, ...], shown: list[str | None]) -> bool:
    """Tell whether try's classes contradict the answer, either way; an all-NULL column
    tells nothing."""
    if len(tried) != len(shown):
        return True
    return any(s is not None and s != t for t, s in zip(tried, shown, strict=True))


def _unseen(found: Verdict) -> set[str]:
    """Return the refusals try says it cannot see: the database's own, and dead tokens."""
    return {"db_error"} | ({"invalid_token"} if found.tokens else set())


def _shown(answer: dict[str, object]) -> list[str | None] | None:
    """Return, per output column of a web answer, what its non-null cells are.

    A column with a value link is a pseudonym; one with a non-null cell and no link is a
    value (a masked cell is a link too, ``/m/``, so it counts as a value); all NULL: None.
    """
    rows = answer.get("rows")
    if not isinstance(rows, list) or not rows:
        return None  # no row to tell by
    out: list[str | None] = []
    for i in range(len(rows[0])):
        cells = [str(row[i]) for row in rows if row[i] is not None]
        linked = any(LINK in c for c in cells)
        out.append(PSEUDONYM if linked else VALUE if cells else None)
    return out


@pytest.fixture(scope="module")
def catalog(world_db: Path) -> Catalog:
    engine = make_engine(f"sqlite:///{world_db.as_posix()}", "sqlite")
    try:
        return reflect(engine, "sqlite")
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def profiled(
    world: World, world_db: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[Path, dict[str, Run]]]:
    """A gateway per output mode and per wider profile, each with its own config."""
    place = tmp_path_factory.mktemp("try-runs")
    runs = open_runs(place, world, "sqlite", f"sqlite:///{world_db.as_posix()}", PROFILES)
    yield place, runs
    for run in runs.values():
        run.gateway.close()


@pytest.mark.no_cover
@pytest.mark.parametrize("name", RUNS)
def test_try_and_query_agree_on_the_corpus(
    profiled: tuple[Path, dict[str, Run]], catalog: Catalog, name: str
) -> None:
    place, runs = profiled
    run = runs[name]
    decl = load_declaration(place / f"bench-{name}.yaml")
    mode = "labels" if name == "labels" else "web"
    disagree = []
    for case in (c for c in load_cases() if c.runs_in(mode, "sqlite")):
        connection = f"try-{name}-{case.id}"  # its own budget: none runs out on the way
        if case.setup is not None:
            run.gateway.query(expand(case.setup, run.tokens), connection)
        sql = expand(case.sql, run.tokens)
        found = verdict(sql, decl, catalog)
        answer = run.gateway.query(sql, connection)
        answered = answer.get("error")
        if found.error is not None and found.error != answered:
            disagree.append(f"{case.id}: try {found.error}, query {answered}")
        if found.error is None and answered is not None and answered not in _unseen(found):
            disagree.append(f"{case.id}: try answered, query {answered}")
        shown = _shown(answer) if mode == "web" and answered is None else None
        if shown is not None and found.error is None and _differs(found.outputs, shown):
            disagree.append(f"{case.id}: try outputs {found.outputs}, query {shown}")
    assert disagree == [], "\n".join(disagree)
