"""The attack corpus on all five DBMS in both modes and every profile: no leak, outcomes hold."""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text

from bench.adapters.incognito import IncognitoAdapter
from bench.build import build_file, file_state
from bench.cases import Case, load_cases
from bench.check import (
    Watch,
    check_case,
    counted,
    expected_state,
    pool_sizes,
    selection_problems,
)
from bench.dbms import Database, load
from bench.fuzz.run import fuzz
from bench.harness import MODES, Run, log_text, open_runs
from bench.oracle import leaks
from bench.profiles import PROFILES
from bench.ruled import HIDDEN_KEYS
from bench.world import World, generate_world

pytestmark = pytest.mark.integration
SEED = 15
CASES = load_cases()
PARAMS = [
    pytest.param(case, mode, profile, id=f"{profile}-{mode}-{case.id}")
    for profile in PROFILES
    for case in CASES
    for mode in MODES
]
ORDERED = [
    pytest.param(c, profile, id=f"{profile}-{c.id}")
    for profile in PROFILES
    for c in CASES
    if c.order_sensitive
]


@dataclass
class Bench:
    """The bench world on one DBMS: gateways, pool sizes, and a direct reading of its state."""

    profiles: dict[str, dict[str, Run]]  # gateways per mode, under each profile
    pools: dict[str, int]
    watch: Watch

    @property
    def runs(self) -> dict[str, Run]:
        """The gateways per mode the corpus expects (strict)."""
        return self.profiles["strict"]


def _fetch(engine: Engine, sql: str) -> list[tuple[object, ...]]:
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql))]


def _build(backend: Database, world: World, directory: Path, admins: list[Engine]) -> Bench:
    """Put the bench world next to the matrix world; open gateways as the reader."""
    if backend.dialect in {"sqlite", "duckdb"}:
        path = directory / f"bench.{backend.dialect}"
        pools = build_file(world, backend.dialect, path, CASES)
        dsn, watch = f"{backend.dialect}:///{path.as_posix()}", Watch.start(file_state(path))
    else:
        load(backend, world.statements(backend.dialect))
        admin = create_engine(backend.admin)
        admins.append(admin)
        fetch = partial(_fetch, admin)
        pools = pool_sizes(CASES, fetch, backend.dialect)
        dsn, watch = backend.url, Watch(partial(counted, fetch, world), expected_state(world))
    profiles = {
        p: open_runs(directory, world, backend.dialect, dsn, protection=p) for p in PROFILES
    }
    return Bench(profiles, pools, watch)


@pytest.fixture(scope="session")
def world() -> World:
    return generate_world(SEED)


@pytest.fixture(scope="session")
def opened() -> Iterator[tuple[dict[str, Bench], list[Engine]]]:
    by_dialect: dict[str, Bench] = {}
    admins: list[Engine] = []
    yield by_dialect, admins
    for bench in by_dialect.values():
        for by_mode in bench.profiles.values():
            for run in by_mode.values():
                run.gateway.close()
    for admin in admins:
        admin.dispose()


@pytest.fixture
def bench(
    backend: Database,
    world: World,
    opened: tuple[dict[str, Bench], list[Engine]],
    tmp_path_factory: pytest.TempPathFactory,
) -> Bench:
    by_dialect, admins = opened
    if backend.dialect not in by_dialect:
        directory = tmp_path_factory.mktemp(f"bench-{backend.dialect}")
        by_dialect[backend.dialect] = _build(backend, world, directory, admins)
    return by_dialect[backend.dialect]


@pytest.mark.parametrize(("case", "mode", "profile"), PARAMS)
def test_case_does_not_leak(  # noqa: PLR0913, PLR0917 -- pytest fixtures
    case: Case,
    mode: str,
    profile: str,
    backend: Database,
    bench: Bench,
    world: World,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    request: pytest.FixtureRequest,
) -> None:
    if not case.runs_in(mode, backend.dialect):
        pytest.skip("case written for other DBMS")
    capfd.readouterr()
    caplog.clear()
    stderr = lambda: capfd.readouterr().err + log_text(caplog.records)  # noqa: E731
    run = bench.profiles[profile][mode]
    outcome, problems = check_case(
        run, case, world.gateway_hidden, stderr, bench.watch, hidden_keys=HIDDEN_KEYS
    )
    request.node.user_properties.append(("outcome", outcome.answer.get("error", "answered")))
    assert problems == []


@pytest.mark.parametrize(("case", "profile"), ORDERED)
def test_selection_varies(case: Case, profile: str, backend: Database, bench: Bench) -> None:
    if backend.dialect not in case.dialects:
        pytest.skip("case written for other DBMS")
    labels = bench.profiles[profile]["labels"]
    assert selection_problems(labels, case, bench.pools[case.id]) == []


@pytest.mark.parametrize("mode", MODES)
def test_describe_does_not_leak_and_open_values_show(mode: str, bench: Bench, world: World) -> None:
    gateway = bench.runs[mode].gateway
    assert leaks(json.dumps(gateway.describe()), world.forbidden) == []
    answer = gateway.query("SELECT city, tier FROM users", "bench-control")
    assert set(leaks(json.dumps(answer), world.visible)) == set(world.visible)


FUZZ_COUNT = 200  # per DBMS here; the scheduled bench run sends many more


def test_random_queries_do_not_leak(backend: Database, bench: Bench, world: World) -> None:
    adapters = [IncognitoAdapter(bench.runs[mode], mode, backend.dialect) for mode in MODES]
    tally = fuzz(adapters, world.planted(backend.dialect), seed=11, count=FUZZ_COUNT)
    assert tally.findings == []
    answered = sum(v for k, v in tally.statuses.items() if k.endswith(":answered"))
    assert answered > tally.sent // 5
