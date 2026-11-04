"""The bench world in a SQLite file and a gateway per output mode."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from bench.build import build_file, file_state
from bench.cases import load_cases
from bench.check import Watch
from bench.harness import Run, open_runs
from bench.world import World, generate_world

SEED = 15


@pytest.fixture(scope="session")
def world() -> World:
    return generate_world(SEED)


Built = tuple[Path, dict[str, int], Watch]


@pytest.fixture(scope="session")
def built(world: World, tmp_path_factory: pytest.TempPathFactory) -> Built:
    """The world file, each order-sensitive case's pool size, and the file read after build."""
    path = tmp_path_factory.mktemp("bench") / "world.db"
    pools = build_file(world, "sqlite", path, load_cases())
    return path, pools, Watch.start(file_state(path))


@pytest.fixture(scope="session")
def world_db(built: Built) -> Path:
    return built[0]


@pytest.fixture(scope="session")
def pools(built: Built) -> dict[str, int]:
    return built[1]


@pytest.fixture(scope="session")
def watch(built: Built) -> Watch:
    return built[2]


@pytest.fixture(scope="session")
def runs(world: World, world_db: Path) -> Iterator[dict[str, Run]]:
    dsn = f"sqlite:///{world_db.as_posix()}"
    opened = open_runs(world_db.parent, world, "sqlite", dsn, profiles=("permissive",))
    yield opened
    for run in opened.values():
        run.gateway.close()
