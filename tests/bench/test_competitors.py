"""Competitor adapters without running them: answer parsing, launch lines, our configs."""

from pathlib import Path

import pytest
import yaml
from launch_lines import hidden_columns, opened

from bench.adapters import launch, mcp_pii_shield, safedb_mcp, sanitized_db_mcp, sql_safe_mcp
from bench.adapters.base import ANSWERED, REFUSED, NotRunError
from bench.dbms import Database
from bench.world import World

CONFIG = launch.CONFIG


def test_answers_are_parsed_into_rows() -> None:
    sql_safe = '{"columns": [{"name": "id"}], "rows": [[1], [2]], "row_count": 2}'
    assert sql_safe_mcp.parse(sql_safe, is_error=False) == (ANSWERED, [[1], [2]])
    assert sql_safe_mcp.parse("Error executing tool", is_error=True) == (REFUSED, None)
    sanitized = '/* 1 rows returned */\n[{"id": 1, "city": "x"}]'
    assert sanitized_db_mcp.parse(sanitized, is_error=False) == (ANSWERED, [[1, "x"]])
    restricted = "Error: Query references restricted columns"
    assert sanitized_db_mcp.parse(restricted, is_error=False)[0] == REFUSED
    safedb = '{"ok": true, "data": {"rows": [{"count": "12"}]}}'
    assert safedb_mcp.parse(safedb, is_error=False) == (ANSWERED, [["12"]])
    assert safedb_mcp.parse('{"ok": false, "error": {}}', is_error=True) == (REFUSED, None)
    assert mcp_pii_shield.parse('[{"n": 3}]', is_error=False) == (ANSWERED, [[3]])
    assert mcp_pii_shield.parse('column "x" does not exist', is_error=True) == (REFUSED, None)


def test_a_container_joins_the_database_as_a_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    db = Database("postgres", "u", "localhost", 5555, None, "abc123", 5432)
    params = launch.container("img", db, {"SECRET_URL": "postgres://x"}, {CONFIG: "/c:ro"}, ["-v"])
    assert params.args[:5] == ["run", "-i", "--rm", "--network", "container:abc123"] or (
        "--user" in params.args
    )
    assert params.args[params.args.index("-e") : params.args.index("-e") + 2] == [
        "-e",
        "SECRET_URL",
    ]
    assert "postgres://x" not in params.args  # passed by name, never on the command line
    assert params.args[-2:] == ["img", "-v"]


def test_missing_docker_is_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    with pytest.raises(NotRunError, match="docker is not installed"):
        launch.ensure_image("img")


def test_sql_safe_config_lists_every_hidden_column(world: World) -> None:
    for dialect in sql_safe_mcp.DIALECTS:
        raw = yaml.safe_load((CONFIG / f"sql_safe_mcp.{dialect}.yaml").read_text("utf-8"))
        rules = raw["servers"]["bench"]["pii"]["rules"]
        listed = {r["table"]: set(r["columns"]) for r in rules}
        for table, columns in hidden_columns(world).items():
            on_dbms = {
                c.name
                for t in world.tables
                if t.name == table
                for c in t.columns
                if c.type_on(dialect)
            }
            assert columns & on_dbms <= listed.get(table, set()), (dialect, table)


def test_safedb_masks_every_hidden_column_of_allowed_tables(world: World) -> None:
    for dialect in safedb_mcp.DIALECTS:
        raw = yaml.safe_load((CONFIG / f"safedb_mcp.{dialect}.yaml").read_text("utf-8"))
        [access] = raw["access"]["schemas"].values()
        masked = {tuple(k.split(".")) for k in access["column_masks"]}
        for table, columns in hidden_columns(world).items():
            if table in access["deny_tables"]:
                continue
            assert table in access["allow_tables"]
            assert {(table, c) for c in columns} - {
                ("ledger", "cash"),
                ("ledger", "huge"),
            } <= masked


def test_sanitized_allowlist_shows_exactly_the_open_and_quasi_columns(world: World) -> None:
    raw = yaml.safe_load((CONFIG / "sanitized_db_mcp.yaml").read_text("utf-8"))
    shown = {(t, c) for t, spec in raw["tables"].items() for c in spec["columns"]}
    visible = {
        (t.name, c.name)
        for t in world.tables
        for c in t.columns
        if c.cls in {"open", "quasi"} and c.type_on("postgres")
    }
    assert shown == visible | {("canary", "id")}


def test_dockerfile_installs_the_pinned_package() -> None:
    text = Path(launch.DOCKERFILES / "sql_safe_mcp.Dockerfile").read_text("utf-8")
    assert "sql-safe-mcp==1.5.2" in text


def test_a_failed_checkout_never_builds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ran: list[list[str]] = []

    def quiet(command: list[str]) -> bool:
        ran.append(command)
        return "checkout" not in command and "inspect" not in command

    monkeypatch.setattr("shutil.which", lambda name: name)
    monkeypatch.setattr(launch, "CACHE", tmp_path)
    monkeypatch.setattr(launch, "_quiet", quiet)
    with pytest.raises(NotRunError, match="checkout"):
        launch.ensure_image("img:1", repo="https://example.test/r", sha="abc")
    assert not [c for c in ran if "build" in c]


def test_a_repository_is_prepared_before_its_dockerfile_builds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ran: list[list[str]] = []

    def quiet(command: list[str]) -> bool:
        ran.append(command)
        return "inspect" not in command

    monkeypatch.setattr("shutil.which", lambda name: name)
    monkeypatch.setattr(launch, "CACHE", tmp_path)
    monkeypatch.setattr(launch, "_quiet", quiet)
    prepare = ("node:20-alpine", "npm ci && npm run build")
    launch.ensure_image("img:1", repo="https://example.test/r", sha="abc", prepare=prepare)
    assert [c[1] for c in ran] == ["image", "clone", "-C", "run", "build"]
    assert ran[3][-4:] == ["node:20-alpine", "sh", "-c", "npm ci && npm run build"]


def test_safedb_mounts_the_sqlite_world_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database("sqlite", "sqlite:///w/world.sqlite", path=Path("w/world.sqlite"))
    args = opened(safedb_mcp, db, monkeypatch)
    assert any(a.endswith(":/data:ro") for a in args)


def test_pii_shield_runs_its_repository_at_the_pinned_commit_over_stdio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("postgres", "u", "localhost", 5555, None, "abc123", 5432)
    args = opened(mcp_pii_shield, db, monkeypatch)
    assert "sha=051534024a87207de8b71f0d68671c2ed6d7a4fd" in args
    assert "repo=https://github.com/thegeekybeng/mcp-pii-shield" in args
    assert args[args.index("TRANSPORT") - 1] == "-e"
    start = args.index("node")
    assert args[start : start + 3] == ["node", "dist/index.js", "--db-uri"]
