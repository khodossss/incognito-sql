"""veil and keeper adapters without running them: answers, launch lines, our configs."""

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from mcp import StdioServerParameters

from bench.adapters import keeper, launch, veil
from bench.adapters.base import ANSWERED, REFUSED
from bench.adapters.mcp_stdio import StdioAdapter
from bench.dbms import Database
from bench.world import World

PG = Database("postgres", "u", "localhost", 5555, None, "abc123", 5432)
SQLITE = Database("sqlite", "sqlite:///w/world.sqlite", path=Path("w/world.sqlite"))


def _hidden(world: World, dialect: str) -> set[tuple[str, str]]:
    return {
        (t.name, c.name)
        for t in world.tables
        for c in t.columns
        if c.cls not in {"open", "quasi"} and c.type_on(dialect) and t.name != "canary"
    } - {("vault", "id")}


def _launch(monkeypatch: pytest.MonkeyPatch, db: Database) -> list[str]:
    """Return veil's launch line and the Dockerfile its image is built from."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr("shutil.which", lambda name: name)
    monkeypatch.setattr(launch, "ensure_image", lambda tag, **kw: seen.update(kw) or tag)
    monkeypatch.setattr(veil, "StdioAdapter", lambda *a, **_kw: seen.update(params=a[2]))
    veil.open_adapter(db, Path("work"))
    params = seen["params"]
    assert isinstance(params, StdioServerParameters)
    return [*params.args, f"dockerfile={seen['dockerfile']}"]


def test_veil_answers_are_parsed_into_rows() -> None:
    text = "id\tname\n1\tFirst_Ab12 Last_Ab12\n2\tNULL\n(2 rows)"
    assert veil.parse(text, is_error=False) == (
        ANSWERED,
        [["1", "First_Ab12 Last_Ab12"], ["2", None]],
    )
    assert veil.parse("n\n(0 rows)", is_error=False) == (ANSWERED, [])
    assert veil.parse("veil-db: read-only", is_error=True) == (REFUSED, None)


def test_veil_sources_are_spelled_as_its_readme_does() -> None:
    assert veil.url(SQLITE) == "/data/world.sqlite"
    assert veil.url(PG).startswith("postgresql://bench_reader:")
    tsql = Database("tsql", "u", inner_port=1433, container="c")
    assert veil.url(tsql) == "mssql://bench_reader:Bench_Reader_1@localhost:1433/world"


def test_veil_mounts_sqlite_read_only_and_passes_keys_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _launch(monkeypatch, SQLITE)
    assert any(a.endswith(":/data:ro") for a in args)
    assert {"VEIL_DB", "VEIL_VAULT_KEY", "VEIL_TOKEN_SECRET"} <= set(args)
    assert "dockerfile=veil.Dockerfile" in args


def test_veil_schema_declares_every_hidden_column(world: World) -> None:
    text = (launch.CONFIG / "veil" / "schema.prisma").read_text("utf-8")
    declared = set()
    for model, body in re.findall(r"model (\w+) \{(.*?)\n\}", text, re.DOTALL):
        declared |= {(model, f) for f in re.findall(r"/// @pii[^\n]*\n\s*(\w+)", body)}
    for dialect in veil.DIALECTS:
        assert _hidden(world, dialect) <= declared, dialect


def test_keeper_answers_are_parsed_into_rows() -> None:
    answer = '{"columns": [{"name": "n"}], "rows": [[1], ["⟨email1:ab⟩"]], "row_count": 2}'
    assert keeper.parse(answer, is_error=False) == (ANSWERED, [[1], ["⟨email1:ab⟩"]])
    assert keeper.parse('{"columns": [], "row_count": 0}', is_error=False) == (ANSWERED, [])
    assert keeper.parse('{"ticket": "t1", "state": "pending_approval"}', is_error=False)[0] == (
        REFUSED
    )
    assert keeper.parse("statement refused", is_error=True) == (REFUSED, None)


def test_keeper_catalog_allows_exactly_the_open_and_quasi_columns(world: World) -> None:
    raw = yaml.safe_load((launch.CONFIG / "keeper" / "catalog.yaml").read_text("utf-8"))
    policies = {
        (t, c): p["policy"] for t, cols in raw["schemas"]["public"].items() for c, p in cols.items()
    }
    on_pg = {
        (t.name, c.name): c.cls for t in world.tables for c in t.columns if c.type_on("postgres")
    }
    assert set(policies) == set(on_pg)
    allowed = {k for k, p in policies.items() if p == "allow"}
    assert allowed == {k for k, cls in on_pg.items() if cls in {"open", "quasi"}}


def test_keeper_queries_name_the_connection_its_container_wrote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr("shutil.which", lambda name: name)
    monkeypatch.setattr(launch, "ensure_image", lambda tag, **_kw: tag)
    monkeypatch.setattr(keeper, "KeeperAdapter", lambda *a, **_kw: seen.update(calls=a[3]))
    keeper.open_adapter(PG, tmp_path)
    arguments = seen["calls"][0]
    assert arguments("SELECT 1") == {"connection_id": "", "sql": "SELECT 1"}
    (tmp_path / "connection_id").write_text("0192-id\n", "utf-8")
    assert arguments("SELECT 1")["connection_id"] == "0192-id"


def test_keeper_states_its_intent_on_every_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[object, ...]] = []
    monkeypatch.setattr(StdioAdapter, "_connect", lambda _self: {"query": {}})
    adapter = object.__new__(keeper.KeeperAdapter)
    client = SimpleNamespace(call_tool=lambda *a: sent.append(a))
    vars(adapter).update(_client=client, _portal=SimpleNamespace(call=lambda f: f()))
    assert adapter._connect() == {"query": {}}
    assert sent[0][:2] == ("set_session_intent", {"intent": keeper.INTENT})


def test_dockerfiles_pin_the_release() -> None:
    veil_file = (launch.DOCKERFILES / "veil.Dockerfile").read_text("utf-8")
    assert "veil-proxy[postgres,mysql,mssql]==0.3.2" in veil_file
    keeper_file = (launch.DOCKERFILES / "keeper.Dockerfile").read_text("utf-8")
    assert "ARG VERSION=0.0.7" in keeper_file
    assert "sha256sum -c" in keeper_file
