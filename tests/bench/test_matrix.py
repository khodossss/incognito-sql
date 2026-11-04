"""The full run's own housekeeping: nothing it creates outlives it."""

import tempfile
from pathlib import Path

import pytest

from bench import matrix
from bench.world import World


def test_the_run_leaves_no_temporary_files(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    report, _facts = matrix.run_all(world, [], [], ["sqlite"], ["raw"], None)
    assert [(r.info.name, r.status) for r in report.rows] == [("raw", "ok")]
    assert list(tmp_path.iterdir()) == []
