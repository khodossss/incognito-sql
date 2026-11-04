"""gate, JanuScope and dbveil without running them: launch lines, images, our configs."""

from pathlib import Path

import pytest
import yaml
from launch_lines import hidden_columns, hidden_names, opened

from bench.adapters import dbveil, gate, januscope, launch
from bench.dbms import Database
from bench.world import World

CONFIG, DOCKERFILES = launch.CONFIG, launch.DOCKERFILES
PG = Database("postgres", "u", "localhost", 5555, None, "abc123", 5432)
MYSQL = Database("mysql", "u", "localhost", 5556, None, "def456", 3306)
LITE = Database("sqlite", "sqlite:///w/world.sqlite", path=Path("w/world.sqlite"))


def _config(name: str) -> dict[str, object]:
    loaded = yaml.safe_load((CONFIG / name).read_text("utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_gate_denies_every_hidden_column_name(world: World) -> None:
    denied = set(_config("gate.yaml")["pii"]["column_denylist"])  # type: ignore[index]
    for dialect in gate.DIALECTS:
        assert hidden_names(world, dialect) <= denied, dialect


def test_gate_runs_its_image_with_logs_in_the_work_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = opened(gate, LITE, monkeypatch)
    assert "dockerfile=gate.Dockerfile" in args
    assert {"GATE_CONFIG", "GATE_LOG_PATH", "GATE_STATS_PATH", "DSN"} <= set(args)
    assert any(a.endswith(":/data:ro") for a in args)
    recipe = (DOCKERFILES / "gate.Dockerfile").read_text("utf-8")
    assert "gate-0.11.6-x86_64-unknown-linux-gnu.tar.gz" in recipe
    assert "@bytebase/dbhub@1.5.0" in recipe


def test_dbveil_rules_cover_every_hidden_column(world: World) -> None:
    rules = _config("dbveil.yaml")["redact"]["columns"]  # type: ignore[index]
    assert hidden_names(world, "postgres") <= {r["column"] for r in rules}
    guard = _config("dbveil.yaml")["guard"]
    assert set(hidden_columns(world)) <= set(guard["pii_tables"])  # type: ignore[index]


def test_dbveil_runs_the_pinned_package(monkeypatch: pytest.MonkeyPatch) -> None:
    args = opened(dbveil, PG, monkeypatch)
    assert {"VEIL_CONFIG", "VEIL_DATABASE_URL", "dockerfile=dbveil.Dockerfile"} <= set(args)
    assert "dbveil==0.2.0" in (DOCKERFILES / "dbveil.Dockerfile").read_text("utf-8")


def test_januscope_redacts_every_hidden_column_on_each_dbms(world: World) -> None:
    for dialect in januscope.DIALECTS:
        rules = _config(f"januscope.{dialect}.yaml")["redact"]["rules"]  # type: ignore[index]
        fields = {r["field"].removeprefix("**.") for r in rules if "field" in r}
        assert hidden_names(world, dialect) <= fields, dialect
        assert "**.name" not in {r.get("field") for r in rules}  # it renames every tool


def test_januscope_names_each_lens_tool_and_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr("shutil.which", lambda name: name)
    monkeypatch.setattr(launch, "ensure_image", lambda tag, **_kw: tag)
    monkeypatch.setattr(januscope, "StdioAdapter", lambda *a, **_kw: calls.append(a))
    for db in (PG, MYSQL, LITE):
        januscope.open_adapter(db, Path("work"))
    assert [c[0].tool for c in calls] == ["execute_sql", "mysql_query", "sqlite_execute"]  # type: ignore[attr-defined]
    assert {"DATABASE_URI"} <= set(calls[0][2].args)  # type: ignore[attr-defined]
    assert {"MYSQL_HOST", "MYSQL_PASS"} <= set(calls[1][2].args)  # type: ignore[attr-defined]
    assert "--config" in calls[2][2].args  # type: ignore[attr-defined]
