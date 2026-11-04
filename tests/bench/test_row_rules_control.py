"""The corpus sees a hole in rules on rows: the same cases fail on a gateway without them."""

from dataclasses import replace
from pathlib import Path

import pytest

from bench.cases import load_cases
from bench.check import Watch, check_case
from bench.harness import open_runs
from bench.ruled import HIDDEN_KEYS
from bench.world import World

CASES = {c.name: c for c in load_cases() if c.category == "row_rules"}


class _Unruled(World):
    """The world whose declaration has lost its rules on rows."""

    def declaration(self, dialect: str, *, web: bool, protection: str = "strict") -> str:
        text = super().declaration(dialect, web=web, protection=protection)
        return text.split("row_rules:")[0]


@pytest.mark.parametrize(
    ("name", "mode", "problem"),
    [
        ("labels of one hidden name", "labels", "label gives a hidden key: patients:3"),
        ("labels of the gone row's name", "labels", "label gives a hidden key: patients:4"),
        ("wards of every patient", "web", "leak in answer"),
    ],
)
def test_a_gateway_without_the_rules_fails_the_cases(  # noqa: PLR0913, PLR0917 -- fixtures
    world: World, world_db: Path, tmp_path: Path, name: str, mode: str, problem: str
) -> None:
    unruled = _Unruled(**{f: getattr(world, f) for f in world.__dataclass_fields__})
    dsn = f"sqlite:///{world_db.as_posix()}"
    runs = open_runs(tmp_path, unruled, "sqlite", dsn)
    try:
        case = replace(CASES[name], mode=mode)
        _, problems = check_case(
            runs[mode],
            case,
            world.gateway_hidden,
            lambda: "",
            Watch(lambda: None, None),
            hidden_keys=HIDDEN_KEYS,
        )
    finally:
        for run in runs.values():
            run.gateway.close()
    assert any(p.startswith(problem) for p in problems), problems
