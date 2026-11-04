"""dbridge-mcp, mcp-server-conceal and DataCharter, not run: launches, configs, answers."""

import json
import tomllib
from pathlib import Path

import pytest
import yaml
from external_world import QUESTIONS, RECORDS, build
from launch_lines import hidden_columns, hidden_names, opened

from bench.adapters import conceal, datacharter, dbridge_mcp, launch
from bench.adapters.base import ANSWERED, REFUSED, NotRunError
from bench.dbms import Database
from bench.external import containers, masks
from bench.external.work import Work, works
from bench.world import World

CONFIG, DOCKERFILES = launch.CONFIG, launch.DOCKERFILES
PG = Database("postgres", "u", "localhost", 5555, None, "abc123", 5432)
LITE = Database("sqlite", "sqlite:///w/world.sqlite", path=Path("w/world.sqlite"))
_CLOSED_TABLES = {"vault", "canary"}  # DataCharter masks them whole (agent_access)


@pytest.fixture
def work(tmp_path: Path) -> Work:
    path, marking = build(tmp_path)
    return next(iter(works(path, marking, QUESTIONS, RECORDS)))


def test_dbridge_hides_secrets_and_masks_every_other_hidden_column(world: World) -> None:
    config = json.loads((CONFIG / "dbridge_mcp.json").read_text("utf-8"))
    masked = {m["column"] for m in config["maskedColumns"]}
    assert {m["strategy"] for m in config["maskedColumns"]} == {"full"}
    for dialect in dbridge_mcp.DIALECTS:
        assert hidden_names(world, dialect) <= masked | set(config["hiddenColumns"]), dialect
    assert "password_hash" in config["hiddenColumns"]
    assert set(config["blockedTables"]) == _CLOSED_TABLES


def test_dbridge_runs_the_pinned_tarball(monkeypatch: pytest.MonkeyPatch) -> None:
    args = opened(dbridge_mcp, PG, monkeypatch)
    assert {"DBRIDGE_CONFIG", "DBRIDGE_DB_PATH", "dockerfile=dbridge_mcp.Dockerfile"} <= set(args)
    recipe = (DOCKERFILES / "dbridge_mcp.Dockerfile").read_text("utf-8")
    assert "dbridge-mcp-0.7.1.tgz" in recipe
    assert "--checksum=sha256:" in recipe
    assert dbridge_mcp.url(PG) == "postgresql://bench_reader:Bench_Reader_1@localhost:5432/world"
    assert dbridge_mcp.url(LITE) == "/data/world.sqlite"


def test_dbridge_answers_and_refusals() -> None:
    ok = '{"rowCount": 1, "truncated": false, "rows": [{"id": 1, "name": "***"}]}'
    assert dbridge_mcp.parse(ok, is_error=False) == (ANSWERED, [[1, "***"]])
    refused = 'Column "ssn" is restricted and cannot be queried.'
    assert dbridge_mcp.parse(refused, is_error=False) == (REFUSED, None)
    assert dbridge_mcp.parse(ok, is_error=True) == (REFUSED, None)


def test_conceal_runs_its_release_in_front_of_dbhub(monkeypatch: pytest.MonkeyPatch) -> None:
    args = opened(conceal, LITE, monkeypatch)
    assert {"DSN", "dockerfile=conceal.Dockerfile"} <= set(args)
    assert any(a.endswith(":/data:ro") for a in args)
    recipe = (DOCKERFILES / "conceal.Dockerfile").read_text("utf-8")
    assert "releases/download/v0.1.0/mcp-server-conceal-linux-amd64" in recipe
    assert "@bytebase/dbhub@1.5.0" in recipe
    config = tomllib.loads((CONFIG / "conceal.toml").read_text("utf-8"))
    assert config["detection"]["mode"] == "regex"
    assert {"email", "phone", "ssn"} <= set(config["detection"]["patterns"])
    assert config["mapping"]["database_path"].startswith("/audit/")


@pytest.mark.parametrize("dialect", datacharter.DIALECTS)
def test_datacharter_declares_every_hidden_column_pii(world: World, dialect: str) -> None:
    charter = yaml.safe_load(datacharter.charter(dialect))
    source = charter["sources"][datacharter.SOURCE]
    assert charter["version"] == 1
    assert set(source["tables"]) == {t.name for t in world.tables}
    for table, columns in hidden_columns(world, dialect).items():
        if table not in _CLOSED_TABLES:
            assert columns <= set(source["pii"].get(table, [])), (dialect, table)
    assert source["agent_access"]["tables"] == dict.fromkeys(_CLOSED_TABLES, False)
    reference = "${BENCH_DB_PASSWORD}"
    assert source.get("credentials", {}).get("password", reference) == reference


def test_datacharter_runs_the_pinned_wheel_over_a_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("work").mkdir()
    args = opened(datacharter, LITE, monkeypatch)
    assert {"BENCH_DB_PASSWORD", "BENCH_DB_FILE", "dockerfile=datacharter.Dockerfile"} <= set(args)
    assert "/ws" in args  # the workspace, after the image
    assert "type: sqlite" in Path("work/charter.yaml").read_text("utf-8")
    recipe = (DOCKERFILES / "datacharter.Dockerfile").read_text("utf-8")
    assert "datacharter-0.44.0-py3-none-any.whl" in recipe
    assert "--checksum=sha256:" in recipe


@pytest.mark.parametrize(
    ("sql", "sent"),
    [
        ("SELECT name FROM users", "SELECT name FROM bench.users"),
        (
            "SELECT /* users */ u.id FROM Users u JOIN purchases p ON p.user_id = u.id",
            "SELECT /* users */ u.id FROM bench.Users u JOIN bench.purchases p ON p.user_id = u.id",
        ),
        ("SELECT 'users' FROM main.users", "SELECT 'users' FROM main.users"),
        (
            "WITH users AS (SELECT 1 AS id) SELECT id FROM users",
            "WITH users AS (SELECT 1 AS id) SELECT id FROM users",
        ),
        ("SELECT * FROM other", "SELECT * FROM other"),
        ("SELECT * FROM users WHERE (((", "SELECT * FROM users WHERE ((("),
    ],
)
def test_datacharter_qualifies_the_world_tables_only(sql: str, sent: str) -> None:
    assert datacharter.qualify(sql, "sqlite", ["users", "purchases"]) == sent


def test_datacharter_answers_and_refusals() -> None:
    ok = '{"columns": ["id", "name"], "rows": [[1, "\\u2022\\u2022\\u2022"]], "row_count": 1}'
    assert datacharter.parse(ok, is_error=False) == (ANSWERED, [[1, "•••"]])
    denied = "Error: Access denied: column(s) email are masked and cannot be used in WHERE"
    assert datacharter.parse(denied, is_error=False) == (REFUSED, None)


def test_set_configs_follow_the_marking(work: Work) -> None:
    dbridge = json.loads(masks.dbridge(work))
    assert {m["column"] for m in dbridge["maskedColumns"]} == {"full_name", "email", "note"}
    assert dbridge["hiddenColumns"] == []
    source = yaml.safe_load(masks.datacharter(work))["sources"]["bench"]
    assert source["path"] == "/data/shop.sqlite"
    assert source["pii"] == {"people": ["full_name", "email"], "orders": ["note"]}


def test_set_launches(work: Work, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch, "ensure_image", lambda tag, **_: tag)
    dbridge = containers._dbridge(work)  # noqa: SLF001
    assert dbridge.env["DBRIDGE_DB_PATH"] == "/data/shop.sqlite"
    assert "dbridge_mcp.json" in dbridge.files
    assert containers._conceal(work).env["DSN"] == "sqlite:///data/shop.sqlite"  # noqa: SLF001
    charter = containers._datacharter(work)  # noqa: SLF001
    assert charter.args == ["/audit"]
    assert "charter.yaml" in charter.work_files
    assert charter.calls[0]("SELECT * FROM people") == {"sql": "SELECT * FROM bench.people"}


def test_datacharter_does_not_run_on_sql_server(tmp_path: Path) -> None:
    tsql = Database("tsql", "u", "localhost", 5555, None, "abc", 1433)
    with pytest.raises(NotRunError, match="TrustServerCertificate"):
        datacharter.open_adapter(tsql, tmp_path)
