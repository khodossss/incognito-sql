"""Output-masking competitors without running them: answers, launch lines, our configs."""

import json
import re
from fnmatch import fnmatch
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from mcp import StdioServerParameters

from bench.adapters import db_results_anonymizer, dbmcp, freepeak_db_mcp, launch
from bench.adapters.base import ANSWERED, REFUSED, NotRunError
from bench.dbms import Database
from bench.world import World

PG = Database("postgres", "u", "localhost", 5555, None, "abc123", 5432)
SQLITE = Database("sqlite", "sqlite:///w/world.sqlite", path=Path("w/world.sqlite"))


def _hidden(world: World, dialect: str) -> set[str]:
    """Names of the columns that carry hidden canaries on ``dialect``, ids aside."""
    return {
        c.name
        for t in world.tables
        for c in t.columns
        if c.cls not in {"open", "quasi"} and c.name != "id" and c.type_on(dialect)
    }


def test_freepeak_answers_are_parsed_into_rows() -> None:
    text = "Results:\n\nid\tname\n" + "-" * 80 + "\n1\t***MASKED***\n2\tNULL\n\nTotal rows: 2"
    assert freepeak_db_mcp.parse(text, is_error=False) == (
        ANSWERED,
        [["1", "***MASKED***"], ["2", None]],
    )
    assert freepeak_db_mcp.parse("query execution failed", is_error=True) == (REFUSED, None)


def test_dbmcp_answers_are_parsed_into_rows() -> None:
    assert dbmcp.parse('{"rows": [{"n": 3, "e": "<EMAIL_ADDRESS>"}]}', is_error=False) == (
        ANSWERED,
        [[3, "<EMAIL_ADDRESS>"]],
    )
    assert dbmcp.parse("Query rejected", is_error=True) == (REFUSED, None)


def test_anonymizer_answers_are_parsed_into_rows() -> None:
    text = '{"columns": ["id"], "rows": [[1], [2]], "row_count": 2}'
    assert db_results_anonymizer.parse(text, is_error=False) == (ANSWERED, [[1], [2]])
    assert db_results_anonymizer.parse('{"error": "Multi-statements"}', is_error=False) == (
        REFUSED,
        None,
    )


def test_freepeak_rules_cover_every_hidden_column_name(world: World) -> None:
    for dialect in freepeak_db_mcp.DIALECTS:
        raw = json.loads((launch.CONFIG / f"freepeak_db_mcp.{dialect}.json").read_text("utf-8"))
        [conn] = raw["connections"]
        assert conn["mask_pii"] is True
        assert conn["read_only"] is True
        rules = [re.compile(r["pattern"]) for r in conn["masking_rules"]]  # Go and Python agree
        for column in _hidden(world, dialect):
            assert any(r.fullmatch(column) for r in rules), (dialect, column)
        assert not any(r.fullmatch(c) for r in rules for c in ("id", "user_id", "city", "tier"))


def test_anonymizer_classifies_every_column(world: World) -> None:
    raw = yaml.safe_load((launch.CONFIG / "db_results_anonymizer.yaml").read_text("utf-8"))
    levels = raw["detection"]["sensitivity"]
    patterns = [p for ps in raw["detection"]["column_patterns"].values() for p in ps]
    assert "vault" in raw["security"]["blocked_tables"]
    for t in world.tables:
        for c in t.columns:
            if not any(c.type_on(d) for d in db_results_anonymizer.DIALECTS):
                continue
            name = c.name.lower()
            if c.cls in {"open", "quasi"}:
                assert name in levels["public"], name
            elif t.name not in {"vault", "canary"}:
                hidden = levels["secret"] + levels["confidential"]
                assert name in hidden or any(fnmatch(name, p) for p in patterns), name


def _launched(module: ModuleType, db: Database, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Return the launch line of ``module``'s tool and how its image was asked for."""
    asked: dict[str, object] = {}
    monkeypatch.setattr("shutil.which", lambda name: name)
    monkeypatch.setattr(launch, "ensure_image", lambda tag, **kw: asked.update(kw) or tag)
    monkeypatch.setattr(module, "StdioAdapter", lambda *a, **_kw: asked.update(params=a[2]))
    module.open_adapter(db, Path("work"))
    params = asked.pop("params")
    assert isinstance(params, StdioServerParameters)
    assert all(v not in params.args for v in ("u", PG.password))  # secrets by name only
    return [*params.args, *(f"{k}={v}" for k, v in asked.items())]


def test_freepeak_builds_the_release_tag_and_runs_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    args = _launched(freepeak_db_mcp, SQLITE, monkeypatch)
    assert f"sha={freepeak_db_mcp.SHA}" in args
    assert any(a.endswith(":/data:ro") for a in args)
    start = args.index("/app/server")
    assert args[start : start + 5] == [
        "/app/server",
        "-t",
        "stdio",
        "-c",
        "/config/freepeak_db_mcp.sqlite.json",
    ]


def test_dbmcp_reaches_the_database_by_its_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    args = _launched(dbmcp, PG, monkeypatch)
    assert "dockerfile=dbmcp.Dockerfile" in args
    assert args[-2] == "stdio"
    assert dbmcp.environment(PG)["DB_PORT"] == "5432"
    assert dbmcp.environment(PG)["PII_NER_ENABLE"] == "true"
    assert dbmcp.environment(SQLITE) == {
        "DB_BACKEND": "sqlite",
        "DB_NAME": "/data/world.sqlite",
        **dbmcp.PII,
    }


def test_anonymizer_runs_stdio_with_its_config(monkeypatch: pytest.MonkeyPatch) -> None:
    args = _launched(db_results_anonymizer, PG, monkeypatch)
    assert "dockerfile=db_results_anonymizer.Dockerfile" in args
    assert args[args.index("MCP_TRANSPORT") - 1] == "-e"
    mssql = Database("tsql", "u", "localhost", 5555, None, "abc123", 1433)
    with pytest.raises(NotRunError, match="readonly"):
        db_results_anonymizer.open_adapter(mssql, Path("work"))


def test_dockerfiles_pin_their_bases() -> None:
    for name in ("dbmcp.Dockerfile", "db_results_anonymizer.Dockerfile"):
        text = Path(launch.DOCKERFILES / name).read_text("utf-8")
        assert re.search(r"^FROM \S+@sha256:[0-9a-f]{64}$", text, re.MULTILINE), name
